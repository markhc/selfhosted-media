"""Offline checks for autobrr's validation and generated configuration."""

from pathlib import Path
import tempfile
import unittest

import yaml

from rolefixture import ROOT, TEMP_ROOT, assert_cases_fail_validation, run_role, validate_task


SETTINGS = {
    "caddy_enabled": True,
    "qbittorrent_enabled": True,
    "autobrr_enabled": True,
    "autobrr_hostname": "autobrr.example.com",
}


def render(directory, variables):
    result = run_role("autobrr", directory, variables, ("compose.yml",))
    if result.returncode:
        raise AssertionError(result.stdout)
    return yaml.safe_load((Path(directory) / "compose.yml").read_text())["services"]["autobrr"]


class AutobrrTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="autobrr-test-", dir=TEMP_ROOT)
        cls.directory = Path(cls.temp.name)
        result = run_role("autobrr", cls.directory, SETTINGS, ("compose.yml",))
        if result.returncode:
            raise AssertionError(result.stdout)
        cls.compose = yaml.safe_load((cls.directory / "compose.yml").read_text())

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_loopback_only_unprivileged_and_hardened(self):
        self.assertEqual(self.compose["name"], "selfhosted-autobrr")
        service = self.compose["services"]["autobrr"]
        self.assertEqual(service["image"], "ghcr.io/autobrr/autobrr:v1.89.0")
        self.assertEqual(service["network_mode"], "host")
        self.assertNotIn("ports", service)
        self.assertEqual(service["user"], "1000:1000")
        self.assertTrue(service["read_only"])
        self.assertEqual(service["cap_drop"], ["ALL"])
        self.assertEqual(service["security_opt"], ["no-new-privileges:true"])
        self.assertEqual(service["tmpfs"], ["/tmp"])
        self.assertEqual(service["volumes"], ["./config:/config"])
        self.assertEqual(service["environment"], {
            "AUTOBRR__HOST": "127.10.0.4", "AUTOBRR__PORT": "7474",
            "AUTOBRR__CORS_ALLOWED_ORIGINS": "https://autobrr.example.com",
            "AUTOBRR__LOG_LEVEL": "INFO", "AUTOBRR__CHECK_FOR_UPDATES": "false", "TZ": "UTC"})
        self.assertEqual(service["healthcheck"]["test"][-1],
                         "http://127.10.0.4:7474/api/healthz/readiness")
        self.assertEqual(service["extra_hosts"], ["autobrr:127.10.0.4", "qbittorrent:127.10.0.1"])

    def test_address_and_runtime_settings_can_be_overridden(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            service = render(temp, {**SETTINGS, "autobrr_address": "127.10.9.9", "autobrr_port": 7500,
                                    "autobrr_log_level": "DEBUG", "autobrr_timezone": "America/Sao_Paulo",
                                    "autobrr_uid": 1001, "autobrr_gid": 1002})
        self.assertEqual(service["user"], "1001:1002")
        self.assertEqual(service["environment"]["AUTOBRR__HOST"], "127.10.9.9")
        self.assertEqual(service["environment"]["AUTOBRR__PORT"], "7500")
        self.assertEqual(service["environment"]["AUTOBRR__LOG_LEVEL"], "DEBUG")
        self.assertEqual(service["environment"]["TZ"], "America/Sao_Paulo")
        self.assertIn("autobrr:127.10.9.9", service["extra_hosts"])

    def test_published_through_caddy(self):
        tasks = {task["name"]: task for task in yaml.safe_load(
            (ROOT / "ansible/roles/autobrr/tasks/main.yml").read_text())}
        publish = tasks["Publish autobrr through Caddy"]
        self.assertEqual(publish["ansible.builtin.include_role"]["tasks_from"], "site")
        self.assertEqual(publish["vars"], {
            "caddy_site_name": "autobrr", "caddy_site_hostname": "{{ autobrr_hostname }}",
            "caddy_site_upstream": "{{ autobrr_listen_address }}:{{ autobrr_port }}"})

    def test_invalid_inputs_fail(self):
        cases = [
            {"caddy_enabled": False},
            {"autobrr_hostname": "Not A Hostname"},
            {"autobrr_port": 80},
            {"autobrr_log_level": "info"},
            {"autobrr_uid": 0},
            {"autobrr_gid": 0},
            {"autobrr_timezone": "../etc/passwd"},
            {"autobrr_directory": "relative/path"},
            {"autobrr_address": "127.0.0.1"},
            {"autobrr_address": "127.10.0.1"},
        ]
        assert_cases_fail_validation(self, self.directory, SETTINGS, cases, [validate_task("autobrr")])


if __name__ == "__main__":
    unittest.main()
