"""Offline checks for monitoring validation and generated configuration."""

import json
from pathlib import Path
import tempfile
import unittest

import yaml

from rolefixture import ROOT, TEMP_ROOT, assert_cases_fail_validation, run_role, validate_task


SETTINGS = {
    "caddy_enabled": True,
    "node_exporter_enabled": True,
    "cadvisor_enabled": True,
    "prometheus_enabled": True,
    "loki_enabled": True,
    "alloy_enabled": True,
    "grafana_enabled": True,
    "grafana_hostname": "grafana.example.com",
    "grafana_admin_password": "not-a-real-password",
    "alloy_docker_socket": {"stat": {"gid": 998}},
}


def render(role, directory, templates):
    result = run_role(role, directory, SETTINGS, templates)
    if result.returncode:
        raise AssertionError(result.stdout)


class MonitoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="monitoring-test-", dir=TEMP_ROOT)
        cls.directory = Path(cls.temp.name)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_exporters_are_loopback_only(self):
        for role, service_name, expected_address in (
                ("node_exporter", "node-exporter", "127.20.0.3"),
                ("cadvisor", "cadvisor", "127.20.0.4")):
            with self.subTest(role=role), tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
                render(role, temp, ("compose.yml",))
                service = yaml.safe_load((Path(temp) / "compose.yml").read_text())["services"][service_name]
                self.assertEqual(service["network_mode"], "host")
                self.assertNotIn("ports", service)
                self.assertIn(expected_address, " ".join(service["command"]))
                if role == "cadvisor":
                    self.assertEqual(service["healthcheck"]["test"][-1],
                                     "http://127.20.0.4:8080/healthz")
        node = yaml.safe_load((ROOT / "ansible/roles/node_exporter/templates/compose.yml.j2").read_text()
                              .replace("{{ node_exporter_image }}", "example/image:1")
                              .replace("{{ node_exporter_listen_address }}", "127.20.0.3")
                              .replace("{{ node_exporter_port }}", "9100"))["services"]["node-exporter"]
        self.assertEqual(node["cap_drop"], ["ALL"])
        self.assertEqual(node["volumes"], ["/:/host:ro,rslave"])

    def test_prometheus_scrapes_selected_exporters_and_bounds_storage(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            render("prometheus", temp, ("compose.yml", "prometheus.yml"))
            compose = yaml.safe_load((Path(temp) / "compose.yml").read_text())["services"]["prometheus"]
            config = yaml.safe_load((Path(temp) / "prometheus.yml").read_text())
        self.assertIn("--storage.tsdb.retention.time=15d", compose["command"])
        self.assertIn("--storage.tsdb.retention.size=5GB", compose["command"])
        targets = {job["job_name"]: job["static_configs"][0]["targets"][0]
                   for job in config["scrape_configs"]}
        self.assertEqual(targets["node"], "127.20.0.3:9100")
        self.assertEqual(targets["cadvisor"], "127.20.0.4:8080")

    def test_loki_is_bounded_and_uses_tsdb_retention(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            render("loki", temp, ("compose.yml", "loki.yml"))
            compose = yaml.safe_load((Path(temp) / "compose.yml").read_text())["services"]["loki"]
            config = yaml.safe_load((Path(temp) / "loki.yml").read_text())
        self.assertEqual(compose["mem_limit"], "512m")
        self.assertEqual(config["schema_config"]["configs"][0]["store"], "tsdb")
        self.assertEqual(config["schema_config"]["configs"][0]["schema"], "v13")
        self.assertEqual(config["limits_config"]["retention_period"], "168h")
        self.assertTrue(config["compactor"]["retention_enabled"])
        self.assertFalse(config["analytics"]["reporting_enabled"])

    def test_alloy_collects_docker_logs_without_publishing_diagnostics(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            render("alloy", temp, ("compose.yml", "config.alloy"))
            compose = yaml.safe_load((Path(temp) / "compose.yml").read_text())["services"]["alloy"]
            config = (Path(temp) / "config.alloy").read_text()
        self.assertNotIn("ports", compose)
        self.assertEqual(compose["mem_limit"], "256m")
        self.assertEqual(compose["user"], "473:473")
        self.assertEqual(compose["group_add"], ["998"])
        self.assertIn("/var/run/docker.sock:/var/run/docker.sock:ro", compose["volumes"])
        self.assertIn('loki.source.docker "containers"', config)
        self.assertIn("forward_to = [loki.write.local.receiver]", config)
        self.assertNotIn("stage.docker", config)
        self.assertIn("http://127.20.0.5:3100/loki/api/v1/push", config)

    def test_grafana_provisions_private_data_sources_and_uses_a_secret(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            render("grafana", temp, ("compose.yml", "datasources.yml"))
            compose = yaml.safe_load((Path(temp) / "compose.yml").read_text())
            sources = yaml.safe_load((Path(temp) / "datasources.yml").read_text())["datasources"]
        service = compose["services"]["grafana"]
        self.assertNotIn("ports", service)
        self.assertEqual(service["environment"]["GF_SERVER_HTTP_ADDR"], "127.20.0.1")
        self.assertEqual(service["environment"]["GF_SECURITY_ADMIN_PASSWORD__FILE"],
                         "/run/secrets/admin_password")
        self.assertEqual(service["environment"]["GF_PLUGINS_PREINSTALL_AUTO_UPDATE"],
                         "false")
        self.assertNotIn("GF_PLUGINS_PREINSTALL_SYNC", service["environment"])
        self.assertIn("Host: grafana.example.com", service["healthcheck"]["test"][-1])
        self.assertIn("http://127.20.0.1:3000/api/health",
                      service["healthcheck"]["test"][-1])
        self.assertNotIn("not-a-real-password", json.dumps(compose))
        self.assertEqual({source["name"]: source["url"] for source in sources}, {
            "Prometheus": "http://127.20.0.2:9090", "Loki": "http://127.20.0.5:3100"})

    def test_grafana_is_published_through_caddy(self):
        tasks = {task["name"]: task for task in yaml.safe_load(
            (ROOT / "ansible/roles/grafana/tasks/main.yml").read_text())}
        publish = tasks["Publish Grafana through Caddy"]
        self.assertEqual(publish["ansible.builtin.include_role"]["tasks_from"], "site")
        self.assertEqual(publish["vars"]["caddy_site_name"], "grafana")

    def test_node_exporter_full_dashboard_is_pinned_and_provisioned(self):
        defaults = yaml.safe_load(
            (ROOT / "ansible/roles/grafana/defaults/main.yml").read_text())
        self.assertEqual(defaults["grafana_node_exporter_full_revision"], 45)
        self.assertEqual(defaults["grafana_node_exporter_full_checksum"],
                         "sha256:184c6b7409f306da75525d7772f71945b10cea23ad16b5d78c4698ea0ea51986")

        tasks = {task["name"]: task for task in yaml.safe_load(
            (ROOT / "ansible/roles/grafana/tasks/main.yml").read_text())}
        download = tasks["Download the pinned Node Exporter Full dashboard"]
        self.assertEqual(download["ansible.builtin.get_url"]["checksum"],
                         "{{ grafana_node_exporter_full_checksum }}")
        self.assertIn("node-exporter-full.json",
                      download["ansible.builtin.get_url"]["dest"])
        self.assertIn("node_exporter_enabled", download["when"])

        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            render("node_exporter", temp, ("compose.yml",))
            command = yaml.safe_load((Path(temp) / "compose.yml").read_text())[
                "services"]["node-exporter"]["command"]
        self.assertIn("--collector.processes", command)
        self.assertIn("--collector.tcpstat", command)

    def test_invalid_monitoring_inputs_fail(self):
        cases = [
            {"grafana_address": "127.0.0.1"},
            {"prometheus_address": "127.20.0.1"},
            {"qbittorrent_enabled": True, "qbittorrent_address": "127.20.0.1"},
            {"grafana_hostname": "Not A Hostname"},
        ]
        assert_cases_fail_validation(self, self.directory, SETTINGS, cases,
                                     [validate_task("grafana")])

        result = run_role("grafana", self.directory,
                          {**SETTINGS, "grafana_admin_password": "short"})
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("short", result.stdout)

    def test_alloy_requires_explicit_loki_selection(self):
        assert_cases_fail_validation(self, self.directory, SETTINGS,
                                     [{"loki_enabled": False}], [validate_task("alloy")])


if __name__ == "__main__":
    unittest.main()
