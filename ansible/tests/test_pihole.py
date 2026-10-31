"""Offline checks for Pi-hole's validation, local DNS records, and generated configuration."""

import json
from pathlib import Path
import re
import tempfile
import unittest

import yaml

from rolefixture import ROOT, TEMP_ROOT, assert_cases_fail_validation, run_play, run_role, validate_task


PASSWORD = "example-pihole-password"
SETTINGS = {
    "caddy_enabled": True,
    "caddy_lan_ip": "192.168.50.10",
    "pihole_enabled": True,
    "pihole_hostname": "pihole.example.com",
    "pihole_webui_password": PASSWORD,
    "pihole_site_hostnames": ["audiobooks.example.com", "sonarr.example.com"],
}


def tasks(name):
    path = ROOT / "ansible/roles/pihole/tasks" / name
    return {task["name"]: task for task in yaml.safe_load(path.read_text())}


class PiholeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="pihole-test-", dir=TEMP_ROOT)
        cls.directory = Path(cls.temp.name)
        result = run_role("pihole", cls.directory, SETTINGS, ("compose.yml",))
        if result.returncode:
            raise AssertionError(result.stdout)
        cls.output = result.stdout
        cls.rendered = (cls.directory / "compose.yml").read_text()
        cls.compose = yaml.safe_load(cls.rendered)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_dns_on_the_lan_address_and_web_interface_on_shared_network(self):
        self.assertEqual(self.compose["name"], "selfhosted-pihole")
        service = self.compose["services"]["pihole"]
        self.assertEqual(service["image"], "pihole/pihole:2026.10.0")
        self.assertEqual(service["networks"], ["selfhosted"])
        self.assertEqual(service["ports"], ["192.168.50.10:53:53/tcp", "192.168.50.10:53:53/udp"])
        environment = service["environment"]
        self.assertEqual(environment["FTLCONF_dns_listeningMode"], "ALL")
        self.assertNotIn("FTLCONF_misc_dnsmasq_lines", environment)
        self.assertEqual(environment["FTLCONF_dns_upstreams"], "1.1.1.1;1.0.0.1")
        self.assertEqual(environment["FTLCONF_webserver_port"], "0.0.0.0:8053")
        self.assertEqual(environment["FTLCONF_webserver_domain"], "pihole.example.com")
        for key in ("FTLCONF_ntp_ipv4_active", "FTLCONF_ntp_ipv6_active", "FTLCONF_ntp_sync_active"):
            self.assertEqual(environment[key], "false")
        self.assertEqual((environment["PIHOLE_UID"], environment["PIHOLE_GID"], environment["TZ"]),
                         ("1000", "1000", "UTC"))
        self.assertEqual(service["healthcheck"]["test"][-2:], ["@127.0.0.1", "pi.hole"])
        self.assertEqual(service["volumes"], ["./etc-pihole:/etc/pihole"])

    def test_capabilities_are_limited_to_the_start_script_and_dns(self):
        service = self.compose["services"]["pihole"]
        self.assertEqual(service["cap_drop"], ["ALL"])
        self.assertEqual(service["cap_add"], ["CHOWN", "DAC_OVERRIDE", "FOWNER", "KILL", "NET_BIND_SERVICE",
                                              "SETFCAP", "SETGID", "SETPCAP", "SETUID"])

    def test_every_caddy_hostname_resolves_to_the_caddy_lan_address(self):
        environment = self.compose["services"]["pihole"]["environment"]
        self.assertEqual(environment["FTLCONF_dns_hostRecord"],
                         "audiobooks.example.com,pihole.example.com,sonarr.example.com,192.168.50.10")

    def test_dns_address_can_differ_from_caddy(self):
        settings = {**SETTINGS, "pihole_dns_address": "192.168.50.11", "pihole_upstreams": ["9.9.9.9", "::1#5335"]}
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            result = run_role("pihole", temp, settings, ("compose.yml",))
            self.assertEqual(result.returncode, 0, result.stdout)
            service = yaml.safe_load((Path(temp) / "compose.yml").read_text())["services"]["pihole"]
            environment = service["environment"]
        self.assertEqual(service["ports"], ["192.168.50.11:53:53/tcp", "192.168.50.11:53:53/udp"])
        self.assertEqual(environment["FTLCONF_dns_upstreams"], "9.9.9.9;::1#5335")
        self.assertTrue(environment["FTLCONF_dns_hostRecord"].endswith(",192.168.50.10"))

    def test_records_come_from_the_published_caddy_sites(self):
        site = (ROOT / "ansible/roles/caddy/templates/site.caddy.j2").read_text()
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            sites = Path(temp) / "conf/sites"
            sites.mkdir(parents=True)
            for name, hostname in (("sonarr-tv", "sonarr.example.com"), ("qui", "qui.example.com"),
                                   ("qui-copy", "qui.example.com")):
                content = site.replace("{{ caddy_site_name }}", name).replace("{{ caddy_site_hostname }}", hostname)
                (sites / f"{name}.caddy").write_text(content)
            (sites / "notes.txt").write_text("https://ignored.example.com {\n")
            show = {"name": "Show fixture", "ansible.builtin.debug": {
                "msg": "HOSTNAMES={{ pihole_site_hostnames | to_json }}"}}
            result = run_play(temp, {"caddy_directory": temp}, [
                {"name": "Collect fixture", "ansible.builtin.import_role": {"name": "pihole", "tasks_from": "records"}},
                show])
        match = re.search(r'"HOSTNAMES=(.*)"$', result.stdout, re.MULTILINE)
        self.assertTrue(match, result.stdout)
        self.assertEqual(json.loads(match.group(1).replace('\\"', '"')), ["qui.example.com", "sonarr.example.com"])

    def test_password_is_kept_out_of_compose_logs_and_diffs(self):
        self.assertNotIn(PASSWORD, self.rendered)
        self.assertNotIn(PASSWORD, self.output)
        service = self.compose["services"]["pihole"]
        self.assertEqual(service["secrets"], ["webpassword"])
        self.assertEqual(service["environment"]["WEBPASSWORD_FILE"], "webpassword")
        self.assertEqual(self.compose["secrets"], {"webpassword": {"file": "./webpassword"}})
        write = tasks("main.yml")["Write the Pi-hole web interface password"]
        self.assertEqual(write["ansible.builtin.copy"]["mode"], "0600")
        self.assertTrue(write["no_log"])
        self.assertFalse(write["diff"])

    def test_pihole_is_published_through_caddy(self):
        publish = tasks("main.yml")["Publish Pi-hole through Caddy"]
        self.assertEqual(publish["ansible.builtin.include_role"]["tasks_from"], "site")
        self.assertEqual(publish["vars"], {"caddy_site_name": "pihole", "caddy_site_hostname": "{{ pihole_hostname }}",
                                           "caddy_site_upstream": "pihole:{{ pihole_port }}"})

    def test_invalid_inputs_fail(self):
        cases = [
            {"caddy_enabled": False},
            {"pihole_hostname": "Not A Hostname"},
            {"pihole_port": 53},
            {"pihole_uid": 0},
            {"pihole_timezone": "../etc/passwd"},
            {"pihole_webui_password": ""},
            {"pihole_webui_password": "short"},
            {"pihole_webui_password": "long enough\npassword"},
            {"pihole_upstreams": []},
            {"pihole_upstreams": "1.1.1.1"},
            {"pihole_upstreams": ["1.1.1.1;listen-address=0.0.0.0"]},
            {"pihole_upstreams": ["dns.example.com"]},
        ]
        for address in ("", "100.64.0.1", "8.8.8.8", "192.168.050.10", "192.168.1.256", "192.168.1.1\n"):
            cases.append({"caddy_lan_ip": address})
            cases.append({"pihole_dns_address": address})
        assert_cases_fail_validation(self, self.directory, SETTINGS, cases, [validate_task("pihole")],
                                     secrets=["long enough"])


if __name__ == "__main__":
    unittest.main()
