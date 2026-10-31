"""Offline checks for Plex's validation and generated configuration."""

from pathlib import Path
import tempfile
import unittest

import yaml

from rolefixture import ROOT, TEMP_ROOT, assert_cases_fail_validation, run_role, validate_task


SETTINGS = {
    "caddy_enabled": True,
    "plex_enabled": True,
    "sonarr_enabled": True,
    "sonarr_instances": [{"name": "tv", "hostname": "sonarr.example.com"}],
    "plex_hostname": "plex.example.com",
    "selfhosted_data_path": "/srv/example data/$media",
}


def render(directory, variables):
    result = run_role("plex", directory, variables, ("compose.yml",))
    if result.returncode:
        raise AssertionError(result.stdout)
    return yaml.safe_load((Path(directory) / "compose.yml").read_text())["services"]["plex"]


def tasks():
    path = ROOT / "ansible/roles/plex/tasks/main.yml"
    return {task["name"]: task for task in yaml.safe_load(path.read_text())}


class PlexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="plex-test-", dir=TEMP_ROOT)
        cls.directory = Path(cls.temp.name)
        result = run_role("plex", cls.directory, SETTINGS, ("compose.yml",))
        if result.returncode:
            raise AssertionError(result.stdout)
        cls.compose = yaml.safe_load((cls.directory / "compose.yml").read_text())

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_available_only_on_the_shared_network(self):
        self.assertEqual(self.compose["name"], "selfhosted-plex")
        service = self.compose["services"]["plex"]
        self.assertEqual(service["image"], "ghcr.io/hotio/plex:release-1.43.5.11079-b3b13e506")
        self.assertNotIn("network_mode", service)
        self.assertNotIn("ports", service)
        self.assertEqual(service["networks"], ["selfhosted"])
        self.assertNotIn("extra_hosts", service)
        self.assertEqual(service["healthcheck"]["test"][-1], "http://127.0.0.1:32400/identity")

    def test_drops_privileges(self):
        service = self.compose["services"]["plex"]
        self.assertEqual(service["cap_drop"], ["ALL"])
        self.assertEqual(service["cap_add"], ["CHOWN", "DAC_OVERRIDE", "SETGID", "SETUID"])
        self.assertEqual(service["security_opt"], ["no-new-privileges:true"])
        self.assertEqual(service["environment"], {
            "PLEX_ADVERTISE_URL": "https://plex.example.com:443",
            "PUID": "1000", "PGID": "1000", "UMASK": "002", "TZ": "UTC"})

    def test_shared_data_is_read_only_by_default(self):
        volumes = self.compose["services"]["plex"]["volumes"]
        self.assertEqual(volumes, ["./config:/config", {
            "type": "bind", "source": "/srv/example data/$$media", "target": "/data",
            "read_only": True, "bind": {"create_host_path": False}}])

    def test_no_gpu_by_default(self):
        service = self.compose["services"]["plex"]
        self.assertNotIn("devices", service)
        self.assertNotIn("deploy", service)

    def test_dri_hardware_acceleration_passes_the_render_devices(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            service = render(temp, {**SETTINGS, "plex_hardware_acceleration": "dri"})
        self.assertEqual(service["devices"], ["/dev/dri:/dev/dri"])
        self.assertNotIn("deploy", service)

    def test_nvidia_hardware_acceleration_reserves_the_gpus(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            service = render(temp, {**SETTINGS, "plex_hardware_acceleration": "nvidia"})
        self.assertNotIn("devices", service)
        self.assertEqual(service["deploy"]["resources"]["reservations"]["devices"], [{
            "driver": "nvidia", "count": "all", "capabilities": ["gpu", "compute", "utility", "video"]}])

    def test_remote_access_publishes_only_on_the_lan_address(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            service = render(temp, {**SETTINGS, "caddy_lan_ip": "192.168.50.10", "plex_remote_access_port": 12345})
            self.assertEqual(service["ports"], ["192.168.50.10:12345:32400"])
            service = render(temp, {**SETTINGS, "caddy_lan_ip": "192.168.50.10", "plex_remote_access_port": "32400",
                                    "plex_remote_access_address": "10.0.0.20"})
            self.assertEqual(service["ports"], ["10.0.0.20:32400:32400"])
        # Off by default, even with a LAN address.
        self.assertNotIn("ports", self.compose["services"]["plex"])

    def test_settings_can_be_overridden(self):
        settings = {**SETTINGS, "selfhosted_data_uid": 1001,
                    "selfhosted_data_container_path": "/media", "plex_data_read_only": False,
                    "plex_timezone": "America/Sao_Paulo"}
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            service = render(temp, settings)
        self.assertNotIn("ports", service)
        self.assertEqual((service["environment"]["PUID"], service["environment"]["TZ"]),
                         ("1001", "America/Sao_Paulo"))
        self.assertEqual(service["volumes"][1]["target"], "/media")
        self.assertFalse(service["volumes"][1]["read_only"])

    def test_published_through_caddy(self):
        publish = tasks()["Publish Plex through Caddy"]
        self.assertEqual(publish["ansible.builtin.include_role"]["tasks_from"], "site")
        self.assertEqual(publish["vars"], {
            "caddy_site_name": "plex", "caddy_site_hostname": "{{ plex_hostname }}",
            "caddy_site_upstream": "plex:{{ plex_port }}"})

    def test_hardware_prerequisites_are_checked_only_when_selected(self):
        role_tasks = tasks()
        for name, mode in (("Require a GPU render node", "dri"), ("Require the NVIDIA Container Toolkit", "nvidia")):
            with self.subTest(task=name):
                self.assertEqual(role_tasks[name]["when"], f"plex_hardware_acceleration == '{mode}'")

    def test_invalid_inputs_fail(self):
        cases = [
            {"caddy_enabled": False},
            {"plex_hostname": "Not A Hostname"},
            {"plex_uid": 0},
            {"plex_umask": 2},
            {"plex_timezone": "../etc/passwd"},
            {"plex_directory": "relative/path"},
            {"plex_data_read_only": "yes"},
            {"plex_hardware_acceleration": "intel"},
            {"plex_hardware_acceleration": True},
            {"selfhosted_data_container_path": "/config"},
            {"selfhosted_data_container_path": "/app/media"},
            # Remote access needs an unprivileged port and an RFC1918 LAN address.
            {"plex_remote_access_port": 12345},
            {"plex_remote_access_port": 80, "caddy_lan_ip": "192.168.50.10"},
            {"plex_remote_access_port": 65536, "caddy_lan_ip": "192.168.50.10"},
            {"plex_remote_access_port": "12345; rm", "caddy_lan_ip": "192.168.50.10"},
            {"plex_remote_access_port": 12345, "plex_remote_access_address": "0.0.0.0"},
            {"plex_remote_access_port": 12345, "plex_remote_access_address": "100.64.0.1"},
            {"plex_remote_access_port": 12345, "plex_remote_access_address": "203.0.113.10"},
            {"plex_remote_access_port": 12345, "plex_remote_access_address": "192.168.050.10"},
        ]
        # Includes sibling service directories, such as Caddy's token, under the deployment root.
        for path in ("", "relative/path", "/srv/example/", "/srv/../etc", "/", "/opt", "/opt/selfhosted",
                     "/opt/selfhosted/caddy"):
            cases.append({"selfhosted_data_path": path})
        assert_cases_fail_validation(self, self.directory, SETTINGS, cases, [validate_task("plex")])


if __name__ == "__main__":
    unittest.main()
