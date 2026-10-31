"""Offline checks for qui's validation and generated configuration."""

from pathlib import Path
import tempfile
import unittest

import yaml

from rolefixture import ROOT, TEMP_ROOT, assert_cases_fail_validation, run_role, validate_task


SETTINGS = {
    "caddy_enabled": True,
    "qbittorrent_enabled": True,
    "qui_enabled": True,
    "selfhosted_data_path": "/srv/example data/$data",
    "qui_hostname": "qui.example.com",
}


def render(directory, variables):
    result = run_role("qui", directory, variables, ("compose.yml",))
    if result.returncode:
        raise AssertionError(result.stdout)
    return yaml.safe_load((Path(directory) / "compose.yml").read_text())["services"]["qui"]


class QuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="qui-test-", dir=TEMP_ROOT)
        cls.directory = Path(cls.temp.name)
        result = run_role("qui", cls.directory, SETTINGS, ("compose.yml",))
        if result.returncode:
            raise AssertionError(result.stdout)
        cls.compose = yaml.safe_load((cls.directory / "compose.yml").read_text())

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_shared_network_only_and_unprivileged(self):
        self.assertEqual(self.compose["name"], "selfhosted-qui")
        service = self.compose["services"]["qui"]
        self.assertEqual(service["image"], "ghcr.io/autobrr/qui:v1.33.1")
        self.assertEqual(service["networks"], ["selfhosted"])
        self.assertNotIn("ports", service)
        self.assertEqual(service["user"], "1000:1000")
        self.assertTrue(service["read_only"])
        self.assertEqual(service["tmpfs"], ["/tmp"])
        self.assertEqual(service["environment"], {
            "QUI__HOST": "0.0.0.0", "QUI__PORT": "7476",
            "QUI__ALLOWED_HOSTS": "qui.example.com,qui",
            "QUI__SESSION_COOKIE_SECURE": "true", "QUI__DISABLE_SELF_UPDATE": "true",
            "QUI__LOG_LEVEL": "INFO", "UMASK": "002", "TZ": "UTC"})
        self.assertEqual(service["healthcheck"]["test"][-1], "http://127.0.0.1:7476/health")
        self.assertNotIn("extra_hosts", service)

    def test_port_can_be_overridden(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            service = render(temp, {**SETTINGS, "qui_port": 7500})
        self.assertEqual(service["environment"]["QUI__HOST"], "0.0.0.0")
        self.assertEqual(service["environment"]["QUI__PORT"], "7500")
        self.assertEqual(service["environment"]["QUI__ALLOWED_HOSTS"], "qui.example.com,qui")

    def test_sees_the_same_paths_as_qbittorrent(self):
        volumes = self.compose["services"]["qui"]["volumes"]
        self.assertEqual(volumes, ["./config:/config", {
            "type": "bind", "source": "/srv/example data/$$data", "target": "/data",
            "bind": {"create_host_path": False}}])
        mounts = [{"path": "/srv/example/cross $seed", "target": "/cross-seed"},
                  {"path": "/srv/example/watch", "target": "/watch", "read_only": False}]
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            service = render(temp, {**SETTINGS, "selfhosted_data_container_path": "/downloads",
                                    "qbittorrent_mounts": mounts})
        self.assertEqual(service["volumes"][1]["target"], "/downloads")
        self.assertEqual(service["volumes"][2:], [
            {"type": "bind", "source": "/srv/example/cross $$seed", "target": "/cross-seed", "read_only": True,
             "bind": {"create_host_path": False}},
            {"type": "bind", "source": "/srv/example/watch", "target": "/watch", "read_only": False,
             "bind": {"create_host_path": False}}])
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            service = render(temp, {**SETTINGS, "qbittorrent_mounts": mounts, "qui_mounts": []})
        self.assertEqual(len(service["volumes"]), 2)

    def test_published_through_caddy(self):
        tasks = {task["name"]: task for task in yaml.safe_load(
            (ROOT / "ansible/roles/qui/tasks/main.yml").read_text())}
        publish = tasks["Publish qui through Caddy"]
        self.assertEqual(publish["ansible.builtin.include_role"]["tasks_from"], "site")
        self.assertEqual(publish["vars"], {
            "caddy_site_name": "qui", "caddy_site_hostname": "{{ qui_hostname }}",
            "caddy_site_upstream": "qui:{{ qui_port }}"})

    def test_invalid_inputs_fail(self):
        cases = [
            {"caddy_enabled": False},
            {"qui_hostname": "Not A Hostname"},
            {"qui_port": 80},
            {"qui_log_level": "debug"},
            {"qui_uid": 0},
            {"selfhosted_data_umask": 2},
            {"qui_timezone": "../etc/passwd"},
        ]
        for path in ("", "relative/path", "/srv/example/", "/srv/../etc", "/", "/opt", "/opt/selfhosted",
                     "/opt/selfhosted/caddy", "/srv/bad\npath"):
            cases.append({"selfhosted_data_path": path})
        for path in ("", "data", "/data/", "/", "/config", "/tmp", "/usr/local/data"):
            cases.append({"selfhosted_data_container_path": path})
        mount = {"path": "/srv/example/watch", "target": "/watch"}
        for mounts in ("/srv/example/watch", {"watch": mount}, [{"target": "/watch"}],
                       [{**mount, "read_only": "no"}], [mount, {**mount, "path": "/srv/example/other"}],
                       [{**mount, "path": "/opt/selfhosted/caddy"}], [{**mount, "target": "/config"}],
                       [{**mount, "target": "/data/watch"}]):
            cases.append({"qui_mounts": mounts})
        assert_cases_fail_validation(self, self.directory, SETTINGS, cases, [validate_task("qui")])


if __name__ == "__main__":
    unittest.main()
