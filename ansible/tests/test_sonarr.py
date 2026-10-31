"""Offline checks for Sonarr's validation and generated configuration.

ArrChecks also covers Radarr, whose role differs only in its name, port, and image.
"""

from pathlib import Path
import tempfile
import unittest

import yaml

from rolefixture import ROOT, TEMP_ROOT, assert_cases_fail_validation, run_cases, run_role, validate_task


class ArrChecks:
    """Checks shared by the Sonarr and Radarr roles; subclasses set the class attributes."""

    APP = ""
    PORT = 0
    IMAGE = ""
    INSTANCES = []
    API_KEYS = {}

    @classmethod
    def settings(cls):
        return {
            "caddy_enabled": True,
            "qbittorrent_enabled": True,
            "qui_enabled": True,
            f"{cls.APP}_enabled": True,
            "selfhosted_data_path": "/srv/example data/$data",
            f"{cls.APP}_instances": cls.INSTANCES,
            f"{cls.APP}_api_keys": cls.API_KEYS,
        }

    @classmethod
    def render(cls, directory, variables, instance):
        result = run_role(cls.APP, directory, {**variables, f"{cls.APP}_instance": instance}, ("compose.yml",))
        if result.returncode:
            raise AssertionError(result.stdout)
        return yaml.safe_load((Path(directory) / "compose.yml").read_text())

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix=f"{cls.APP}-test-", dir=TEMP_ROOT)
        cls.directory = Path(cls.temp.name)
        cls.compose = cls.render(cls.directory, cls.settings(), cls.INSTANCES[1])

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def tasks(self, name):
        path = ROOT / "ansible/roles" / self.APP / "tasks" / name
        return {task["name"]: task for task in yaml.safe_load(path.read_text())}

    def test_instance_is_shared_network_only_and_drops_privileges(self):
        app, instance = self.APP, self.INSTANCES[1]
        prefix = app.upper() + "__"
        self.assertEqual(self.compose["name"], f"selfhosted-{app}-{instance['name']}")
        service_name = f"{app}-{instance['name']}"
        service = self.compose["services"][service_name]
        self.assertEqual(service["image"], self.IMAGE)
        self.assertEqual(service["networks"], ["selfhosted"])
        self.assertNotIn("ports", service)
        self.assertEqual(service["cap_drop"], ["ALL"])
        self.assertEqual(service["cap_add"], ["CHOWN", "SETGID", "SETUID"])
        self.assertEqual(service["security_opt"], ["no-new-privileges:true"])
        self.assertEqual(service["env_file"], ["./api.env"])
        self.assertEqual(service["environment"], {
            prefix + "SERVER__BINDADDRESS": "0.0.0.0", prefix + "SERVER__PORT": str(self.PORT),
            prefix + "SERVER__ENABLESSL": "false", prefix + "SERVER__URLBASE": "",
            prefix + "SERVER__ALLOWEDHOSTS":
                f"{instance['hostname']},{app}-{instance['name']}",
            prefix + "AUTH__REQUIRED": "Enabled", prefix + "LOG__LEVEL": "info",
            "PUID": "1000", "PGID": "1000", "UMASK": "002", "TZ": "UTC"})
        self.assertEqual(service["healthcheck"]["test"][-1], f"http://127.0.0.1:{self.PORT}/ping")
        self.assertNotIn("extra_hosts", service)
        self.assertEqual(service["volumes"], ["./config:/config", {
            "type": "bind", "source": "/srv/example data/$$data", "target": "/data",
            "bind": {"create_host_path": False}}])
        rendered = (self.directory / "compose.yml").read_text()
        for key in self.API_KEYS.values():
            self.assertNotIn(key, rendered)

    def test_shared_settings_can_be_overridden(self):
        settings = {**self.settings(), "selfhosted_data_container_path": "/downloads", "selfhosted_data_uid": 1001,
                    "selfhosted_data_umask": "022", f"{self.APP}_timezone": "America/Sao_Paulo",
                    f"{self.APP}_log_level": "debug"}
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            service_name = f"{self.APP}-{self.INSTANCES[0]['name']}"
            service = self.render(temp, settings, self.INSTANCES[0])["services"][service_name]
        environment = service["environment"]
        self.assertEqual((environment["PUID"], environment["UMASK"], environment["TZ"]),
                         ("1001", "022", "America/Sao_Paulo"))
        self.assertEqual(environment[self.APP.upper() + "__LOG__LEVEL"], "debug")
        self.assertEqual(service["volumes"][1]["target"], "/downloads")

    def test_each_instance_is_deployed_and_published_separately(self):
        app = self.APP
        deploy = self.tasks("main.yml")[f"Deploy each {app.capitalize()} instance"]
        self.assertEqual(deploy["ansible.builtin.include_tasks"], "instance.yml")
        self.assertEqual(deploy["loop"], f"{{{{ {app}_instances }}}}")
        self.assertEqual(deploy["loop_control"]["loop_var"], f"{app}_instance")
        tasks = self.tasks("instance.yml")
        publish = tasks[f"Publish the Caddy site for {{{{ {app}_instance_name }}}}"]
        self.assertEqual(publish["ansible.builtin.include_role"]["tasks_from"], "site")
        self.assertEqual(publish["vars"], {
            "caddy_site_name": f"{{{{ {app}_instance_name }}}}",
            "caddy_site_hostname": f"{{{{ {app}_instance.hostname }}}}",
            "caddy_site_upstream": f"{{{{ {app}_instance_name }}}}:{{{{ {app}_port }}}}"})
        converge = tasks[f"Converge {{{{ {app}_instance_name }}}}"]["community.docker.docker_compose_v2"]
        self.assertEqual(converge["project_name"], f"selfhosted-{{{{ {app}_instance_name }}}}")

    def test_api_key_is_kept_out_of_logs_and_diffs(self):
        app = self.APP
        tasks = self.tasks("instance.yml")
        write = tasks[f"Write the API key for {{{{ {app}_instance_name }}}}"]
        self.assertEqual(write["ansible.builtin.copy"]["content"],
                         f"{app.upper()}__AUTH__APIKEY={{{{ {app}_api_keys[{app}_instance.name] }}}}\n")
        self.assertEqual(write["ansible.builtin.copy"]["mode"], "0600")
        self.assertTrue(write["no_log"])
        self.assertFalse(write["diff"])
        self.assertTrue(tasks[f"Converge {{{{ {app}_instance_name }}}}"]["no_log"])

    def test_invalid_inputs_fail(self):
        app, instances = self.APP, self.INSTANCES
        first = instances[0]
        cases = [
            {"caddy_enabled": False},
            {f"{app}_instances": []},
            {f"{app}_instances": "instance"},
            {f"{app}_instances": {"name": "instance"}},
            {f"{app}_instances": ["instance"]},
            {f"{app}_instances": [{"hostname": first["hostname"]}]},
            {f"{app}_instances": [{key: value for key, value in first.items() if key != "hostname"}]},
            {f"{app}_instances": [{**first, "hostname": "Not A Hostname"}]},
            {f"{app}_instances": [first, {**instances[1], "hostname": first["hostname"]}]},
            {f"{app}_instances": [first, {**instances[1], "name": first["name"]}]},
            {f"{app}_instances": [{**first, "name": "Bad_Name"}]},
            {f"{app}_port": 80},
            {f"{app}_log_level": "Info"},
            {f"{app}_uid": 0},
            {"selfhosted_data_umask": 2},
            {f"{app}_timezone": "../etc/passwd"},
        ]
        for path in ("", "relative/path", "/srv/example/", "/srv/../etc", "/", "/opt", "/opt/selfhosted",
                     "/opt/selfhosted/caddy", "/srv/bad\npath"):
            cases.append({"selfhosted_data_path": path})
        for path in ("", "data", "/data/", "/", "/app", "/config", "/tmp", "/usr/local/data"):
            cases.append({"selfhosted_data_container_path": path})
        assert_cases_fail_validation(self, self.directory, self.settings(), cases, [validate_task(app)])

    def test_invalid_api_keys_fail_without_leaking(self):
        app = self.APP
        names = [instance["name"] for instance in self.INSTANCES]
        keys = self.API_KEYS
        invalid = ["0123456789ABCDEF0123456789ABCDEF", "0123456789abcdef", "secret-api-key-that-is-not-hex!!"]
        cases = [{}, {app + "_api_keys": "0123456789abcdef0123456789abcdef"},
                 {app + "_api_keys": {names[0]: keys[names[0]]}},
                 {app + "_api_keys": {names[0]: keys[names[0]], names[1]: keys[names[0]]}}]
        cases += [{app + "_api_keys": {**keys, names[1]: value}} for value in invalid]
        settings = {key: value for key, value in self.settings().items() if key != app + "_api_keys"}
        result, outcomes = run_cases(self.directory, [{**settings, **extra} for extra in cases],
                                     [validate_task(app)])
        for extra, outcome in zip(cases, outcomes):
            with self.subTest(extra=extra):
                self.assertTrue(outcome["failed"], result.stdout)
        for secret in [*keys.values(), *invalid]:
            self.assertNotIn(secret, result.stdout)


class SonarrTests(ArrChecks, unittest.TestCase):
    APP = "sonarr"
    PORT = 8989
    IMAGE = "ghcr.io/hotio/sonarr:release-4.0.20.3014"
    INSTANCES = [
        {"name": "tv", "hostname": "sonarr.example.com"},
        {"name": "anime", "hostname": "anime.example.com"},
    ]
    API_KEYS = {"tv": "0123456789abcdef0123456789abcdef", "anime": "fedcba9876543210fedcba9876543210"}


if __name__ == "__main__":
    unittest.main()
