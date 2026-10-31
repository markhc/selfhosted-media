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

from rolefixture import (ROOT, TEMP_ROOT, assert_cases_fail_validation, run_cases, run_play, run_role,
                         validate_task)


PASSWORD = "fake-qbittorrent-password-for-tests"
SETTINGS = {
    "caddy_enabled": True,
    "qbittorrent_enabled": True,
    "selfhosted_data_path": "/srv/example data/$data",
    "qbittorrent_confirm_legal_notice": True,
    "qbittorrent_hostname": "torrents.example.com",
    "qbittorrent_webui_username": "exampleuser",
    "qbittorrent_webui_password": PASSWORD,
}
# qBittorrent before 5.3 reads its WebUI settings from [Preferences] WebUI\\* keys.
PREFERENCES_CONF = """[BitTorrent]
Session\\DefaultSavePath=/data/torrents

[Preferences]
WebUI\\Address=*
WebUI\\Port=8080
WebUI\\LocalHostAuth=false
WebUI\\Username=admin
WebUI\\Password_PBKDF2="@ByteArray(c2FsdA==:a2V5)"
Downloads\\SavePath=/data/torrents
"""
# qBittorrent 5.3 and later read them from a [WebUI] section.
WEBUI_CONF = """[BitTorrent]
Session\\DefaultSavePath=/data/torrents

[Preferences]
Downloads\\SavePath=/data/torrents

[WebUI]
Address=*
Port=8080
LocalHostAuth=false
Username=admin
Password_PBKDF2="@ByteArray(c2FsdA==:a2V5)"
"""


def webui_section(text):
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read_string(text)
    return parser


def webui_settings(text, section="Preferences", prefix="WebUI\\"):
    """Return the WebUI settings stored in SECTION under PREFIX, without the prefix."""
    parser = webui_section(text)
    if not parser.has_section(section):
        return {}
    return {key[len(prefix):]: value for key, value in parser[section].items() if key.startswith(prefix)}


def verify_pbkdf2(value, password):
    """Check VALUE the way qBittorrent's Utils::Password::PBKDF2::verify does."""
    match = re.fullmatch(r'"@ByteArray\(([A-Za-z0-9+/=]+):([A-Za-z0-9+/=]+)\)"', value)
    if not match:
        return False
    salt, key = (base64.b64decode(part) for part in match.groups())
    return len(salt) == 16 and hashlib.pbkdf2_hmac("sha512", password.encode(), salt, 100000, 64) == key


CONVERGE_TASKS = [{"name": "Converge fixture", "ansible.builtin.import_role": {
    "name": "qbittorrent", "tasks_from": "conf"}}]


def conf_variables(directory, extra=None):
    """Return the settings that converge the qBittorrent configuration in DIRECTORY."""
    return {**SETTINGS, "qbittorrent_directory": str(directory),
            "qbittorrent_uid": os.getuid(), "qbittorrent_gid": os.getgid(), **(extra or {})}


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
        return run_play(directory, conf_variables(directory, extra), CONVERGE_TASKS)

    def test_webui_on_shared_network_and_peer_ports_published(self):
        self.assertEqual(self.compose["name"], "selfhosted-qbittorrent")
        service = self.compose["services"]["qbittorrent"]
        self.assertEqual(service["image"], "qbittorrentofficial/qbittorrent-nox:5.2.4-1")
        self.assertEqual(service["networks"], ["selfhosted"])
        self.assertEqual(service["ports"], ["6881:6881/tcp", "6881:6881/udp"])
        self.assertEqual(service["user"], "1000:1000")
        self.assertTrue(service["read_only"])
        self.assertEqual(service["stop_grace_period"], "30m")
        self.assertEqual(service["environment"], {
            "QBT_LEGAL_NOTICE": "confirm", "QBT_WEBUI_PORT": "8080", "QBT_TORRENTING_PORT": "6881",
            "UMASK": "002", "TZ": "UTC"})
        self.assertEqual(service["healthcheck"]["test"][-1], "http://127.0.0.1:8080/")
        self.assertNotIn("extra_hosts", service)

    def test_peer_selection_does_not_change_the_project(self):
        instances = [{"name": "tv"}, {"name": "anime"}]
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            variables = {**SETTINGS, "sonarr_enabled": True, "sonarr_instances": instances}
            result = run_role("qbittorrent", temp, variables, ("compose.yml", "qBittorrent.conf"))
            self.assertEqual(result.returncode, 0, result.stdout)
            service = yaml.safe_load((Path(temp) / "compose.yml").read_text())["services"]["qbittorrent"]
            # Selecting another media service must not recreate qBittorrent.
            self.assertNotIn("extra_hosts", service)
            self.assertEqual(service["healthcheck"]["test"][-1], "http://127.0.0.1:8080/")
            self.assertEqual(webui_settings((Path(temp) / "qBittorrent.conf").read_text())["Address"],
                              "0.0.0.0")

    def test_shared_data_root_is_an_existing_bind_mount(self):
        volumes = self.compose["services"]["qbittorrent"]["volumes"]
        self.assertEqual(volumes, ["./config:/config", {
            "type": "bind", "source": "/srv/example data/$$data", "target": "/data",
            "bind": {"create_host_path": False}}])

    def test_data_container_path_can_match_an_existing_stack(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            variables = {**SETTINGS, "selfhosted_data_container_path": "/downloads"}
            result = run_role("qbittorrent", temp, variables, ("compose.yml", "qBittorrent.conf"))
            self.assertEqual(result.returncode, 0, result.stdout)
            service = yaml.safe_load((Path(temp) / "compose.yml").read_text())["services"]["qbittorrent"]
            self.assertEqual(service["volumes"][1]["target"], "/downloads")
            conf = webui_section((Path(temp) / "qBittorrent.conf").read_text())
            self.assertEqual(conf["BitTorrent"]["Session\\DefaultSavePath"], "/downloads/torrents")

    def test_additional_mounts_are_existing_binds_read_only_by_default(self):
        mounts = [{"path": "/srv/example/cross $seed", "target": "/cross-seed"},
                  {"path": "/srv/example/watch", "target": "/watch", "read_only": False}]
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            result = run_role("qbittorrent", temp, {**SETTINGS, "qbittorrent_mounts": mounts}, ("compose.yml",))
            self.assertEqual(result.returncode, 0, result.stdout)
            volumes = yaml.safe_load((Path(temp) / "compose.yml").read_text())["services"]["qbittorrent"]["volumes"]
        self.assertEqual(volumes[2:], [
            {"type": "bind", "source": "/srv/example/cross $$seed", "target": "/cross-seed", "read_only": True,
             "bind": {"create_host_path": False}},
            {"type": "bind", "source": "/srv/example/watch", "target": "/watch", "read_only": False,
             "bind": {"create_host_path": False}}])

    def test_seed_configuration_binds_loopback_with_hashed_credentials(self):
        text = (self.directory / "qBittorrent.conf").read_text()
        conf = webui_section(text)
        self.assertEqual(conf["BitTorrent"]["Session\\DefaultSavePath"], "/data/torrents")
        self.assertEqual(conf["BitTorrent"]["Session\\DisableAutoTMMByDefault"], "false")
        self.assertFalse(conf.has_section("WebUI"))
        webui = webui_settings(text)
        self.assertEqual(webui["Address"], "0.0.0.0")
        self.assertEqual(webui["Port"], "8080")
        self.assertEqual(webui["LocalHostAuth"], "true")
        self.assertEqual(webui["AuthSubnetWhitelistEnabled"], "false")
        self.assertEqual(webui["TrustedReverseProxiesList"], "172.30.0.2")
        self.assertEqual(webui["Username"], "exampleuser")
        self.assertTrue(verify_pbkdf2(webui["Password_PBKDF2"], PASSWORD))
        self.assertNotIn(PASSWORD, (self.directory / "qBittorrent.conf").read_text())

    def test_password_hash_is_stable_per_host_and_user(self):
        def hashed(host, user):
            with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
                variables = {**SETTINGS, "qbittorrent_webui_username": user}
                result = run_role("qbittorrent", temp, variables, ("qBittorrent.conf",), host=host)
                self.assertEqual(result.returncode, 0, result.stdout)
                return webui_settings((Path(temp) / "qBittorrent.conf").read_text())["Password_PBKDF2"]
        first = hashed("nas_server", "exampleuser")
        self.assertEqual(first, hashed("nas_server", "exampleuser"))
        self.assertNotEqual(first, hashed("other_nas", "exampleuser"))

    def test_migrated_configuration_is_converged_where_the_release_reads_it(self):
        # (pinned tag, existing configuration, section and prefix it reads, stale location)
        cases = [
            ("5.2.4-1", PREFERENCES_CONF, ("Preferences", "WebUI\\"), ("WebUI", "")),
            ("5.2.4-1", WEBUI_CONF, ("Preferences", "WebUI\\"), ("WebUI", "")),
            ("5.3.0-2", PREFERENCES_CONF, ("WebUI", ""), ("Preferences", "WebUI\\")),
            ("5.3.0-2", WEBUI_CONF, ("WebUI", ""), ("Preferences", "WebUI\\")),
        ]
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            # Every case converges its own directory as its own host, in one run per pass.
            hosts = []
            for index, (tag, existing, _, _) in enumerate(cases):
                directory = Path(temp) / str(index)
                conf_path = directory / "config/qBittorrent/config/qBittorrent.conf"
                conf_path.parent.mkdir(parents=True)
                conf_path.write_text(existing)
                hosts.append(conf_variables(directory, {"qbittorrent_image_tag": tag}))
            first, first_outcomes = run_cases(temp, hosts, CONVERGE_TASKS)
            second, second_outcomes = run_cases(temp, hosts, CONVERGE_TASKS)
            for index, (tag, existing, current, stale) in enumerate(cases):
                with self.subTest(tag=tag, existing=existing):
                    self.assertEqual(first_outcomes[index]["failed"], 0, first.stdout)
                    text = (Path(temp) / str(index) / "config/qBittorrent/config/qBittorrent.conf").read_text()
                    webui = webui_settings(text, *current)
                    self.assertEqual(webui["Address"], "0.0.0.0")
                    self.assertEqual(webui["LocalHostAuth"], "true")
                    self.assertTrue(verify_pbkdf2(webui["Password_PBKDF2"], PASSWORD))
                    self.assertEqual(webui_settings(text, *stale), {})
                    conf = webui_section(text)
                    self.assertEqual(conf["Preferences"]["Downloads\\SavePath"], "/data/torrents")
                    self.assertEqual(conf["BitTorrent"]["Session\\DefaultSavePath"], "/data/torrents")
                    self.assertEqual(second_outcomes[index]["failed"], 0, second.stdout)
                    self.assertEqual(second_outcomes[index]["changed"], 0, second.stdout)

    def test_newer_release_is_seeded_with_a_webui_section(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            variables = {**SETTINGS, "qbittorrent_image_tag": "5.3.0-2"}
            result = run_role("qbittorrent", temp, variables, ("qBittorrent.conf",))
            self.assertEqual(result.returncode, 0, result.stdout)
            text = (Path(temp) / "qBittorrent.conf").read_text()
            self.assertEqual(webui_settings(text), {})
            webui = webui_settings(text, "WebUI", "")
            self.assertEqual(webui["Address"], "0.0.0.0")
            self.assertTrue(verify_pbkdf2(webui["Password_PBKDF2"], PASSWORD))

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
            conf_path.write_text(WEBUI_CONF)
            result = self.converge_conf(temp)
            self.assertEqual(result.returncode, 0, result.stdout)
            password_hash = webui_settings(conf_path.read_text())["Password_PBKDF2"].strip('"')
            for secret in (PASSWORD, password_hash):
                self.assertNotIn(secret, result.stdout)
        self.assertNotIn(PASSWORD, self.result.stdout)

    def test_webui_stays_published_next_to_qui(self):
        tasks = {task["name"]: task for task in yaml.safe_load(
            (ROOT / "ansible/roles/qbittorrent/tasks/main.yml").read_text())}
        publish = tasks["Publish the qBittorrent WebUI through Caddy"]
        self.assertEqual(publish["ansible.builtin.include_role"]["tasks_from"], "site")
        self.assertEqual(publish["vars"]["caddy_site_upstream"],
                          "qbittorrent:{{ qbittorrent_webui_port }}")
        self.assertEqual(publish["when"], "not ansible_check_mode")
        # The fallback WebUI needs Caddy and a hostname even when qui is selected.
        without_hostname = {key: value for key, value in SETTINGS.items() if key != "qbittorrent_hostname"}
        result = run_role("qbittorrent", self.directory, {**without_hostname, "qui_enabled": True})
        self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_invalid_inputs_fail(self):
        cases = [
            {"qbittorrent_confirm_legal_notice": False},
            {"qbittorrent_confirm_legal_notice": "yes"},
            {"caddy_enabled": False},
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
            {"qbittorrent_image_tag": "4.6.7-1"},
            {"qbittorrent_image_tag": "5.2"},
            {"qbittorrent_image_tag": "release-5.2.4"},
        ]
        for path in ("", "relative/path", "/srv/example/", "/srv/../etc", "/", "/opt", "/opt/selfhosted",
                     "/opt/selfhosted/caddy", "/srv/bad\npath"):
            cases.append({"selfhosted_data_path": path})
        for path in ("", "data", "/data/", "/", "/data/../etc", "/my data", "/config", "/config/data", "/tmp",
                     "/usr/local/data", "/proc"):
            cases.append({"selfhosted_data_container_path": path})
        mount = {"path": "/srv/example/watch", "target": "/watch"}
        for mounts in ("/srv/example/watch", {"watch": mount}, ["/srv/example/watch"],
                       [{"target": "/watch"}], [{"path": "/srv/example/watch"}],
                       [{**mount, "read_only": "no"}], [mount, {**mount, "path": "/srv/example/other"}],
                       [mount, {"path": "/srv/example/other", "target": "/watch/inner"}],
                       [{"path": "/srv/example/other", "target": "/watch/inner"}, mount]):
            cases.append({"qbittorrent_mounts": mounts})
        for path in ("relative/path", "/srv/example/", "/srv/../etc", "/", "/opt/selfhosted",
                     "/opt/selfhosted/caddy"):
            cases.append({"qbittorrent_mounts": [{**mount, "path": path}]})
        for target in ("watch", "/watch/", "/", "/config", "/tmp/watch", "/etc", "/data", "/data/watch", "/my watch"):
            cases.append({"qbittorrent_mounts": [{**mount, "target": target}]})
        assert_cases_fail_validation(self, self.directory, SETTINGS, cases, [validate_task("qbittorrent")],
                                     secrets=(PASSWORD,))


if __name__ == "__main__":
    unittest.main()
