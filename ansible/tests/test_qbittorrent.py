"""Offline checks for qBittorrent's validation, generated configuration, and settings convergence."""

import base64
import configparser
import hashlib
import os
from pathlib import Path
import re
import tempfile
import unittest

import yaml

from rolefixture import ROOT, TEMP_ROOT, run_play, run_role


PASSWORD = "fake-qbittorrent-password-for-tests"
SETTINGS = {
    "selfhosted_services": {"caddy": {"enabled": True}, "qbittorrent": {"enabled": True}},
    "selfhosted_data_path": "/srv/example data/$data",
    "qbittorrent_confirm_legal_notice": True,
    "qbittorrent_hostname": "torrents.example.com",
    "qbittorrent_webui_username": "exampleuser",
    "qbittorrent_webui_password": PASSWORD,
}
LEGACY_CONF = """[BitTorrent]
Session\\DefaultSavePath=/data/torrents

[Preferences]
WebUI\\Address=*
WebUI\\Port=8080
WebUI\\LocalHostAuth=false
WebUI\\Username=admin
WebUI\\Password_PBKDF2="@ByteArray(c2FsdA==:a2V5)"
Downloads\\SavePath=/data/torrents
"""


def webui_section(text):
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read_string(text)
    return parser


def verify_pbkdf2(value, password):
    """Check VALUE the way qBittorrent's Utils::Password::PBKDF2::verify does."""
    match = re.fullmatch(r'"@ByteArray\(([A-Za-z0-9+/=]+):([A-Za-z0-9+/=]+)\)"', value)
    if not match:
        return False
    salt, key = (base64.b64decode(part) for part in match.groups())
    return len(salt) == 16 and hashlib.pbkdf2_hmac("sha512", password.encode(), salt, 100000, 64) == key


class QbittorrentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="qbittorrent-test-", dir=TEMP_ROOT)
        cls.directory = Path(cls.temp.name)
        cls.result = run_role("qbittorrent", cls.directory, SETTINGS, ("compose.yml", "qBittorrent.conf"))
        if cls.result.returncode:
            raise AssertionError(cls.result.stdout)
        cls.compose = yaml.safe_load((cls.directory / "compose.yml").read_text())

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def converge_conf(self, directory, extra=None):
        variables = {**SETTINGS, "qbittorrent_directory": str(directory),
                     "qbittorrent_uid": os.getuid(), "qbittorrent_gid": os.getgid(), **(extra or {})}
        tasks = [{"name": "Resolve fixture", "ansible.builtin.include_role": {"name": "media_hosts"}},
                 {"name": "Converge fixture", "ansible.builtin.import_role": {
                     "name": "qbittorrent", "tasks_from": "conf"}}]
        return run_play(directory, variables, tasks)

    def test_webui_on_loopback_and_unprivileged(self):
        self.assertEqual(self.compose["name"], "selfhosted-qbittorrent")
        service = self.compose["services"]["qbittorrent"]
        self.assertEqual(service["image"], "qbittorrentofficial/qbittorrent-nox:5.3.0-2")
        self.assertEqual(service["network_mode"], "host")
        self.assertNotIn("ports", service)
        self.assertEqual(service["user"], "1000:1000")
        self.assertTrue(service["read_only"])
        self.assertEqual(service["stop_grace_period"], "30m")
        self.assertEqual(service["environment"], {
            "QBT_LEGAL_NOTICE": "confirm", "QBT_WEBUI_PORT": "8080", "QBT_TORRENTING_PORT": "6881",
            "UMASK": "002", "TZ": "UTC"})
        self.assertEqual(service["healthcheck"]["test"][-1], "http://127.10.0.1:8080/")
        self.assertEqual(service["extra_hosts"], ["qbittorrent:127.10.0.1"])

    def test_peers_resolve_by_name_and_address_can_be_overridden(self):
        services = {**SETTINGS["selfhosted_services"], "sonarr": {"enabled": True}}
        instances = [{"name": "tv", "address": "127.10.1.1"}, {"name": "anime", "address": "127.10.1.2"}]
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            variables = {**SETTINGS, "selfhosted_services": services, "sonarr_instances": instances,
                         "qbittorrent_address": "127.10.9.9"}
            result = run_role("qbittorrent", temp, variables, ("compose.yml", "qBittorrent.conf"))
            self.assertEqual(result.returncode, 0, result.stdout)
            service = yaml.safe_load((Path(temp) / "compose.yml").read_text())["services"]["qbittorrent"]
            self.assertEqual(service["extra_hosts"], [
                "qbittorrent:127.10.9.9", "sonarr-anime:127.10.1.2", "sonarr-tv:127.10.1.1"])
            self.assertEqual(webui_section((Path(temp) / "qBittorrent.conf").read_text())["WebUI"]["Address"],
                             "127.10.9.9")

    def test_shared_data_root_is_an_existing_bind_mount(self):
        volumes = self.compose["services"]["qbittorrent"]["volumes"]
        self.assertEqual(volumes, ["./config:/config", {
            "type": "bind", "source": "/srv/example data/$$data", "target": "/data",
            "bind": {"create_host_path": False}}])

    def test_seed_configuration_binds_loopback_with_hashed_credentials(self):
        conf = webui_section((self.directory / "qBittorrent.conf").read_text())
        self.assertEqual(conf["BitTorrent"]["Session\\DefaultSavePath"], "/data/torrents")
        self.assertEqual(conf["BitTorrent"]["Session\\DisableAutoTMMByDefault"], "false")
        webui = conf["WebUI"]
        self.assertEqual(webui["Address"], "127.10.0.1")
        self.assertEqual(webui["Port"], "8080")
        self.assertEqual(webui["LocalHostAuth"], "true")
        self.assertEqual(webui["AuthSubnetWhitelistEnabled"], "false")
        self.assertEqual(webui["TrustedReverseProxiesList"], "127.0.0.1")
        self.assertEqual(webui["Username"], "exampleuser")
        self.assertTrue(verify_pbkdf2(webui["Password_PBKDF2"], PASSWORD))
        self.assertNotIn(PASSWORD, (self.directory / "qBittorrent.conf").read_text())

    def test_password_hash_is_stable_per_host_and_user(self):
        def hashed(host, user):
            with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
                variables = {**SETTINGS, "qbittorrent_webui_username": user}
                result = run_role("qbittorrent", temp, variables, ("qBittorrent.conf",), host=host)
                self.assertEqual(result.returncode, 0, result.stdout)
                return webui_section((Path(temp) / "qBittorrent.conf").read_text())["WebUI"]["Password_PBKDF2"]
        first = hashed("nas_server", "exampleuser")
        self.assertEqual(first, hashed("nas_server", "exampleuser"))
        self.assertNotEqual(first, hashed("other_nas", "exampleuser"))

    def test_migrated_configuration_is_converged_and_idempotent(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            conf_path = Path(temp) / "config/qBittorrent/config/qBittorrent.conf"
            conf_path.parent.mkdir(parents=True)
            conf_path.write_text(LEGACY_CONF)
            first = self.converge_conf(temp)
            self.assertEqual(first.returncode, 0, first.stdout)
            conf = webui_section(conf_path.read_text())
            self.assertEqual(conf["WebUI"]["Address"], "127.10.0.1")
            self.assertEqual(conf["WebUI"]["LocalHostAuth"], "true")
            self.assertTrue(verify_pbkdf2(conf["WebUI"]["Password_PBKDF2"], PASSWORD))
            self.assertEqual([key for key in conf["Preferences"] if key.startswith("WebUI\\")], [])
            self.assertEqual(conf["Preferences"]["Downloads\\SavePath"], "/data/torrents")
            self.assertEqual(conf["BitTorrent"]["Session\\DefaultSavePath"], "/data/torrents")
            second = self.converge_conf(temp)
            self.assertEqual(second.returncode, 0, second.stdout)
            self.assertRegex(second.stdout, r"changed=0\b")

    def test_new_configuration_is_seeded_once(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            (Path(temp) / "config/qBittorrent/config").mkdir(parents=True)
            self.assertEqual(self.converge_conf(temp).returncode, 0)
            second = self.converge_conf(temp)
            self.assertEqual(second.returncode, 0, second.stdout)
            self.assertRegex(second.stdout, r"changed=0\b")

    def test_output_is_redacted(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            conf_path = Path(temp) / "config/qBittorrent/config/qBittorrent.conf"
            conf_path.parent.mkdir(parents=True)
            conf_path.write_text(LEGACY_CONF)
            result = self.converge_conf(temp)
            self.assertEqual(result.returncode, 0, result.stdout)
            password_hash = webui_section(conf_path.read_text())["WebUI"]["Password_PBKDF2"].strip('"')
            for secret in (PASSWORD, password_hash):
                self.assertNotIn(secret, result.stdout)
        self.assertNotIn(PASSWORD, self.result.stdout)

    def test_publication_depends_on_qui_selection(self):
        tasks = {task["name"]: task for task in yaml.safe_load(
            (ROOT / "ansible/roles/qbittorrent/tasks/main.yml").read_text())}
        publish = tasks["Publish the qBittorrent WebUI through Caddy"]
        unpublish = tasks["Unpublish the qBittorrent WebUI in favor of qui"]
        self.assertEqual(publish["ansible.builtin.include_role"]["tasks_from"], "site")
        self.assertEqual(publish["vars"]["caddy_site_upstream"],
                         "{{ qbittorrent_webui_address }}:{{ qbittorrent_webui_port }}")
        self.assertEqual(unpublish["ansible.builtin.include_role"]["tasks_from"], "unpublish")
        self.assertEqual(unpublish["vars"], {"caddy_site_name": "qbittorrent"})
        # Without qui, Caddy and a hostname are required; with qui, neither is.
        with_qui = {"selfhosted_services": {"qbittorrent": {"enabled": True}, "qui": {"enabled": True}}}
        without_hostname = {key: value for key, value in SETTINGS.items() if key != "qbittorrent_hostname"}
        result = run_role("qbittorrent", self.directory, {**without_hostname, **with_qui})
        self.assertEqual(result.returncode, 0, result.stdout)
        result = run_role("qbittorrent", self.directory, without_hostname)
        self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_invalid_inputs_fail(self):
        cases = [
            {"qbittorrent_confirm_legal_notice": False},
            {"qbittorrent_confirm_legal_notice": "yes"},
            {"selfhosted_services": {"qbittorrent": {"enabled": True}}},
            {"qbittorrent_hostname": "Not A Hostname"},
            {"qbittorrent_webui_port": 80},
            {"qbittorrent_torrenting_port": 8080},
            {"qbittorrent_uid": 0},
            {"selfhosted_data_umask": 2},
            {"selfhosted_data_umask": "0022x"},
            {"qbittorrent_timezone": "../etc/passwd"},
            {"qbittorrent_webui_username": ""},
            {"qbittorrent_webui_username": "user=admin"},
            {"qbittorrent_webui_password": "short"},
            {"qbittorrent_webui_password": "fake-password\nWebUI\\Address=*"},
        ]
        for path in ("", "relative/path", "/srv/example/", "/srv/../etc", "/", "/opt", "/opt/selfhosted",
                     "/opt/selfhosted/caddy", "/srv/bad\npath"):
            cases.append({"selfhosted_data_path": path})
        for extra in cases:
            with self.subTest(extra=extra):
                result = run_role("qbittorrent", self.directory, {**SETTINGS, **extra})
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn('"evaluated_to": false', result.stdout)
                self.assertNotIn(PASSWORD, result.stdout)


if __name__ == "__main__":
    unittest.main()
