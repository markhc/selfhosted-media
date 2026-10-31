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
    "caddy_site_upstream": "example:8080",
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
        self.assertIn("bind 0.0.0.0", caddyfile)
        self.assertIn("dns cloudflare {env.CLOUDFLARE_API_TOKEN}", caddyfile)
        self.assertTrue(caddyfile.rstrip().endswith("import sites/*.caddy"))
        self.assertNotIn(TOKEN, caddyfile)

    def test_site_imports_private_listener_and_proxies_over_docker_dns(self):
        site = (self.directory / "site.caddy").read_text()
        self.assertIn("https://app.example.com {", site)
        self.assertIn("import selfhosted_private", site)
        self.assertIn("reverse_proxy example:8080", site)
        self.assertNotIn("bind", site)

    def test_compose_publishes_only_private_https_and_has_no_secrets(self):
        compose = yaml.safe_load((self.directory / "compose.yml").read_text())
        self.assertEqual(compose["name"], "selfhosted-caddy")
        service = compose["services"]["caddy"]
        self.assertEqual(service["ports"], ["100.100.100.100:443:443", "192.168.50.10:443:443"])
        self.assertEqual(service["networks"], {"selfhosted": {"ipv4_address": "172.30.0.2"}})
        self.assertEqual(service["build"], {"context": "./build"})
        self.assertIn("./conf:/etc/caddy:ro", service["volumes"])
        self.assertEqual(service["environment"], {"TZ": "UTC"})
        self.assertNotIn(TOKEN, (self.directory / "compose.yml").read_text())

    def test_build_context_excludes_everything_but_the_dockerfile(self):
        ignore = (ROOT / "ansible/roles/caddy/files/caddy.dockerignore").read_text().split()
        self.assertEqual([line for line in ignore if not line.startswith("#")][-2:], ["*", "!Dockerfile"])

    def test_invalid_inputs_fail_without_leaking_token(self):
        for extra in ({"caddy_cloudflare_api_token": ""}, {"caddy_cloudflare_api_token": "bad\ntoken"},
                      {"caddy_lan_ip": "203.0.113.10"}, {"caddy_lan_ip": "192.168.1.256"},
                      {"caddy_lan_ip": "192.168.01.10"}, {"caddy_directory": "relative"},
                      {"caddy_timezone": "/UTC"},
                      {"web_stack_cloudflare_api_token": TOKEN}, {"web_stack_lan_ip": ""}):
            with self.subTest(extra=extra):
                result = run_role("caddy", self.directory, {**SETTINGS, **extra})
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertNotIn(TOKEN, result.stdout)

    def test_invalid_sites_are_rejected(self):
        validation = yaml.safe_load((ROOT / "ansible/roles/caddy/tasks/site.yml").read_text())[0]
        result = run_play(self.directory, {**SETTINGS, "caddy_site_upstream": "sonarr-tv:8989"}, [validation])
        self.assertEqual(result.returncode, 0, result.stdout)
        for extra in ({"caddy_site_name": "Bad Name"}, {"caddy_site_hostname": "not a hostname"},
                      {"caddy_site_upstream": "0.0.0.0:8080"}, {"caddy_site_upstream": "Bad_Name:8080"},
                      {"caddy_site_upstream": "-service:8080"}, {"caddy_site_upstream": "service:0"},
                      {"caddy_site_upstream": "service:65536"}, {"caddy_site_upstream": "service:8080/path"}):
            with self.subTest(extra=extra):
                result = run_play(self.directory, {**SETTINGS, **extra}, [validation])
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("A Caddy site needs", result.stdout)

    def test_unpublishing_an_absent_site_changes_nothing(self):
        tasks = [{"name": "Unpublish fixture", "ansible.builtin.include_role": {
            "name": "caddy", "tasks_from": "unpublish"}}]
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            (Path(temp) / "conf/sites").mkdir(parents=True)
            (Path(temp) / "conf/sites/other.caddy").write_text("# fixture\n")
            result = run_play(temp, {**SETTINGS, "caddy_directory": temp}, tasks)
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertRegex(result.stdout, r"changed=0\b")
            self.assertTrue((Path(temp) / "conf/sites/other.caddy").exists())
            result = run_play(temp, {**SETTINGS, "caddy_directory": temp, "caddy_site_name": "../other"}, tasks)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("A Caddy site needs", result.stdout)


if __name__ == "__main__":
    unittest.main()
