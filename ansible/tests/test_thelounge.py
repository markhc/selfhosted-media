"""Offline checks for The Lounge's validation and generated configuration."""

from pathlib import Path
import tempfile
import unittest

import yaml

from rolefixture import TEMP_ROOT, run_role


SETTINGS = {
    "caddy_enabled": True,
    "thelounge_enabled": True,
    "thelounge_hostname": "lounge.example.com",
}


class TheLoungeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="thelounge-test-", dir=TEMP_ROOT)
        cls.directory = Path(cls.temp.name)
        result = run_role("thelounge", cls.directory, SETTINGS, ("config.js", "compose.yml"))
        if result.returncode:
            raise AssertionError(result.stdout)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_private_shared_network_behind_reverse_proxy(self):
        config = (self.directory / "config.js").read_text()
        self.assertIn("public: false", config)
        self.assertIn('host: "0.0.0.0"', config)
        self.assertIn("port: 9000", config)
        self.assertIn("reverseProxy: true", config)

    def test_compose_has_no_published_ports(self):
        compose = yaml.safe_load((self.directory / "compose.yml").read_text())
        self.assertEqual(compose["name"], "selfhosted-thelounge")
        service = compose["services"]["thelounge"]
        self.assertEqual(service["networks"], ["selfhosted"])
        self.assertNotIn("ports", service)
        self.assertEqual(service["user"], "1000:1000")
        self.assertEqual(service["environment"], {"TZ": "UTC"})
        self.assertEqual(service["volumes"], ["./data:/var/opt/thelounge"])

    def test_timezone_follows_shared_setting_unless_overridden(self):
        for extra, expected in (({"selfhosted_timezone": "America/Sao_Paulo"}, "America/Sao_Paulo"),
                                ({"selfhosted_timezone": "America/Sao_Paulo", "thelounge_timezone": "Etc/GMT+3"},
                                 "Etc/GMT+3")):
            with self.subTest(extra=extra):
                result = run_role("thelounge", self.directory, {**SETTINGS, **extra}, ("compose.yml",))
                self.assertEqual(result.returncode, 0, result.stdout)
                compose = yaml.safe_load((self.directory / "compose.yml").read_text())
                self.assertEqual(compose["services"]["thelounge"]["environment"], {"TZ": expected})

    def test_invalid_inputs_fail(self):
        for extra in ({"caddy_enabled": False},
                      {"thelounge_hostname": "Not A Hostname"}, {"thelounge_port": 80},
                      {"selfhosted_timezone": "Not A Timezone"}):
            with self.subTest(extra=extra):
                result = run_role("thelounge", self.directory, {**SETTINGS, **extra})
                self.assertNotEqual(result.returncode, 0, result.stdout)


if __name__ == "__main__":
    unittest.main()
