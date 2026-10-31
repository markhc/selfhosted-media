"""Offline checks for Prowlarr's validation and generated configuration."""

from pathlib import Path
import tempfile
import unittest

import yaml

from rolefixture import ROOT, TEMP_ROOT, assert_cases_fail_validation, run_cases, run_role, validate_task


API_KEY = "0123456789abcdef0123456789abcdef"
SETTINGS = {
    "caddy_enabled": True,
    "qui_enabled": True,
    "prowlarr_enabled": True,
    "sonarr_enabled": True,
    "sonarr_instances": [{"name": "tv", "hostname": "sonarr.example.com"}],
    "prowlarr_hostname": "prowlarr.example.com",
    "prowlarr_api_key": API_KEY,
}


def render(directory, variables):
    result = run_role("prowlarr", directory, variables, ("compose.yml",))
    if result.returncode:
        raise AssertionError(result.stdout)
    return yaml.safe_load((Path(directory) / "compose.yml").read_text())["services"]["prowlarr"]


def tasks():
    path = ROOT / "ansible/roles/prowlarr/tasks/main.yml"
    return {task["name"]: task for task in yaml.safe_load(path.read_text())}


class ProwlarrTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="prowlarr-test-", dir=TEMP_ROOT)
        cls.directory = Path(cls.temp.name)
        result = run_role("prowlarr", cls.directory, SETTINGS, ("compose.yml",))
        if result.returncode:
            raise AssertionError(result.stdout)
        cls.compose = yaml.safe_load((cls.directory / "compose.yml").read_text())

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_shared_network_only_and_drops_privileges(self):
        self.assertEqual(self.compose["name"], "selfhosted-prowlarr")
        service = self.compose["services"]["prowlarr"]
        self.assertEqual(service["image"], "ghcr.io/hotio/prowlarr:release-2.6.5.5623")
        self.assertEqual(service["networks"], ["selfhosted"])
        self.assertNotIn("ports", service)
        self.assertEqual(service["cap_drop"], ["ALL"])
        self.assertEqual(service["cap_add"], ["CHOWN", "SETGID", "SETUID"])
        self.assertEqual(service["security_opt"], ["no-new-privileges:true"])
        self.assertEqual(service["env_file"], ["./api.env"])
        self.assertEqual(service["environment"], {
            "PROWLARR__SERVER__BINDADDRESS": "0.0.0.0", "PROWLARR__SERVER__PORT": "9696",
            "PROWLARR__SERVER__ENABLESSL": "false", "PROWLARR__SERVER__URLBASE": "",
            "PROWLARR__SERVER__ALLOWEDHOSTS": "prowlarr.example.com,prowlarr",
            "PROWLARR__AUTH__REQUIRED": "Enabled", "PROWLARR__LOG__LEVEL": "info",
            "PUID": "1000", "PGID": "1000", "TZ": "UTC"})
        self.assertEqual(service["healthcheck"]["test"][-1], "http://127.0.0.1:9696/ping")
        self.assertNotIn("extra_hosts", service)
        # Prowlarr handles no media files.
        self.assertEqual(service["volumes"], ["./config:/config"])
        self.assertNotIn(API_KEY, (self.directory / "compose.yml").read_text())

    def test_settings_can_be_overridden(self):
        settings = {**SETTINGS, "prowlarr_port": 9700, "selfhosted_data_uid": 1001,
                    "prowlarr_timezone": "America/Sao_Paulo", "prowlarr_log_level": "debug"}
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            service = render(temp, settings)
        environment = service["environment"]
        self.assertEqual(environment["PROWLARR__SERVER__BINDADDRESS"], "0.0.0.0")
        self.assertEqual(environment["PROWLARR__SERVER__PORT"], "9700")
        self.assertEqual(environment["PROWLARR__SERVER__ALLOWEDHOSTS"], "prowlarr.example.com,prowlarr")
        self.assertEqual((environment["PUID"], environment["TZ"], environment["PROWLARR__LOG__LEVEL"]),
                         ("1001", "America/Sao_Paulo", "debug"))
        self.assertEqual(service["healthcheck"]["test"][-1], "http://127.0.0.1:9700/ping")

    def test_published_through_caddy(self):
        publish = tasks()["Publish Prowlarr through Caddy"]
        self.assertEqual(publish["ansible.builtin.include_role"]["tasks_from"], "site")
        self.assertEqual(publish["vars"], {
            "caddy_site_name": "prowlarr", "caddy_site_hostname": "{{ prowlarr_hostname }}",
            "caddy_site_upstream": "prowlarr:{{ prowlarr_port }}"})

    def test_api_key_is_kept_out_of_logs_and_diffs(self):
        role_tasks = tasks()
        write = role_tasks["Write the Prowlarr API key"]
        self.assertEqual(write["ansible.builtin.copy"]["content"], "PROWLARR__AUTH__APIKEY={{ prowlarr_api_key }}\n")
        self.assertEqual(write["ansible.builtin.copy"]["mode"], "0600")
        self.assertTrue(write["no_log"])
        self.assertFalse(write["diff"])
        self.assertTrue(role_tasks["Converge Prowlarr"]["no_log"])

    def test_invalid_inputs_fail(self):
        cases = [
            {"caddy_enabled": False},
            {"prowlarr_hostname": "Not A Hostname"},
            {"prowlarr_port": 80},
            {"prowlarr_log_level": "Info"},
            {"prowlarr_uid": 0},
            {"prowlarr_timezone": "../etc/passwd"},
            {"prowlarr_directory": "relative/path"},
        ]
        assert_cases_fail_validation(self, self.directory, SETTINGS, cases, [validate_task("prowlarr")])

    def test_invalid_api_keys_fail_without_leaking(self):
        invalid = ["0123456789ABCDEF0123456789ABCDEF", "0123456789abcdef", "secret-api-key-that-is-not-hex!!"]
        settings = {key: value for key, value in SETTINGS.items() if key != "prowlarr_api_key"}
        cases = [{}, {"prowlarr_api_key": {"key": API_KEY}}] + [{"prowlarr_api_key": value} for value in invalid]
        result, outcomes = run_cases(self.directory, [{**settings, **extra} for extra in cases],
                                     [validate_task("prowlarr")])
        for extra, outcome in zip(cases, outcomes):
            with self.subTest(extra=extra):
                self.assertTrue(outcome["failed"], result.stdout)
        for secret in [API_KEY, *invalid]:
            self.assertNotIn(secret, result.stdout)


if __name__ == "__main__":
    unittest.main()
