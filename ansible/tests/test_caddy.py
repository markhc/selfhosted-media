"""Offline checks for Caddy's validation, generated configuration, and site publishing."""

from pathlib import Path
import tempfile
import unittest

import yaml

from rolefixture import ROOT, TEMP_ROOT, run_play, run_role


TOKEN = "fake-cloudflare-token-for-tests"
SETTINGS = {
    "caddy_cloudflare_api_token": TOKEN,
    "caddy_lan_ip": "192.168.50.10",
    "caddy_tailscale_ip": {"stdout": "100.100.100.100\n"},
    "caddy_site_name": "example",
    "caddy_site_hostname": "app.example.com",
    "caddy_site_upstream": "127.0.0.1:8080",
}


class CaddyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="caddy-test-", dir=TEMP_ROOT)
        cls.directory = Path(cls.temp.name)
        result = run_role("caddy", cls.directory, SETTINGS, ("Caddyfile", "compose.yml", "site.caddy"))
        if result.returncode:
            raise AssertionError(result.stdout)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_private_listeners_and_dns_challenge_are_shared_by_every_site(self):
        caddyfile = (self.directory / "Caddyfile").read_text()
        self.assertIn("auto_https disable_redirects", caddyfile)
        self.assertIn("admin localhost:2019", caddyfile)
        self.assertIn("(selfhosted_private) {", caddyfile)
        self.assertIn("bind 100.100.100.100 192.168.50.10", caddyfile)
        self.assertIn("dns cloudflare {env.CLOUDFLARE_API_TOKEN}", caddyfile)
        self.assertTrue(caddyfile.rstrip().endswith("import sites/*.caddy"))
        self.assertNotIn(TOKEN, caddyfile)

    def test_site_imports_private_listener_and_proxies_to_loopback(self):
        site = (self.directory / "site.caddy").read_text()
        self.assertIn("https://app.example.com {", site)
        self.assertIn("import selfhosted_private", site)
        self.assertIn("reverse_proxy 127.0.0.1:8080", site)
        self.assertNotIn("bind", site)

    def test_compose_has_no_published_ports_or_secrets(self):
        compose = yaml.safe_load((self.directory / "compose.yml").read_text())
        self.assertEqual(compose["name"], "selfhosted-caddy")
        service = compose["services"]["caddy"]
        self.assertEqual(service["network_mode"], "host")
        self.assertNotIn("ports", service)
        self.assertEqual(service["build"], {"context": "./build"})
        self.assertIn("./conf:/etc/caddy:ro", service["volumes"])
        self.assertNotIn(TOKEN, (self.directory / "compose.yml").read_text())

    def test_build_context_excludes_everything_but_the_dockerfile(self):
        ignore = (ROOT / "ansible/roles/caddy/files/caddy.dockerignore").read_text().split()
        self.assertEqual([line for line in ignore if not line.startswith("#")][-2:], ["*", "!Dockerfile"])

    def test_invalid_inputs_fail_without_leaking_token(self):
        for extra in ({"caddy_cloudflare_api_token": ""}, {"caddy_cloudflare_api_token": "bad\ntoken"},
                      {"caddy_lan_ip": "203.0.113.10"}, {"caddy_lan_ip": "192.168.1.256"},
                      {"caddy_lan_ip": "192.168.01.10"}, {"caddy_directory": "relative"},
                      {"web_stack_cloudflare_api_token": TOKEN}, {"web_stack_lan_ip": ""}):
            with self.subTest(extra=extra):
                result = run_role("caddy", self.directory, {**SETTINGS, **extra})
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertNotIn(TOKEN, result.stdout)

    def test_invalid_sites_are_rejected(self):
        validation = yaml.safe_load((ROOT / "ansible/roles/caddy/tasks/site.yml").read_text())[0]
        for extra in ({"caddy_site_name": "Bad Name"}, {"caddy_site_hostname": "not a hostname"},
                      {"caddy_site_upstream": "0.0.0.0:8080"}, {"caddy_site_upstream": "192.168.1.5:8080"}):
            with self.subTest(extra=extra):
                result = run_play(self.directory, {**SETTINGS, **extra}, [validation])
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("A Caddy site needs", result.stdout)


if __name__ == "__main__":
    unittest.main()
