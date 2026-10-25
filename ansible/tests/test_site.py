"""Offline checks for service selection in the site playbook."""

import json
import re
import tempfile
import unittest

import yaml
from ansible.plugins.filter.core import FilterModule
from ansible.plugins.filter.mathstuff import FilterModule as MathFilterModule
from jinja2 import Environment

from rolefixture import ROOT, TEMP_ROOT, run_play


PLAY = yaml.safe_load((ROOT / "ansible/playbooks/site.yml").read_text())[0]
ROLES = {role["role"]: role for role in PLAY["roles"]}


def expression(source):
    env = Environment()
    env.filters.update(FilterModule().filters())
    env.filters.update(MathFilterModule().filters())
    return env.compile_expression(source.strip().removeprefix("{{").removesuffix("}}"))


SHOW = {"name": "Show fixture", "ansible.builtin.debug": {"msg": "SELECTED={{ selfhosted_selected | to_json }}"}}
VALIDATION = [task for task in PLAY["pre_tasks"] if task["name"] in (
    "Refuse the former selection map", "Validate the service selection")]


def run_selection(directory, flags, tasks=(SHOW,)):
    return run_play(directory, {**PLAY["vars"], **flags}, list(tasks))


def selected(directory, flags):
    result = run_selection(directory, flags)
    match = re.search(r'"SELECTED=(.*)"$', result.stdout, re.MULTILINE)
    if result.returncode or not match:
        raise AssertionError(result.stdout)
    return json.loads(match.group(1).replace('\\"', '"'))


def group_vars(group):
    return yaml.safe_load((ROOT / f"ansible/inventories/example/group_vars/{group}.yml").read_text())


class SiteSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="site-test-", dir=TEMP_ROOT)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_only_explicitly_enabled_services_are_selected(self):
        self.assertEqual(selected(self.temp.name, {}), [])
        self.assertEqual(selected(self.temp.name, {"caddy_enabled": True, "thelounge_enabled": False,
                                                   "plex_enabled": True}), ["caddy"])
        self.assertEqual(PLAY["vars"]["selfhosted_service_names"],
                         ["tailscale" if role == "nas_tailscale" else role
                          for role in ROLES if role != "docker_runtime"])

    def test_each_service_role_is_tagged_and_gated_by_its_own_key(self):
        for name in ("caddy", "thelounge", "audiobookshelf", "qbittorrent", "qui", "sonarr", "radarr", "znc"):
            with self.subTest(role=name):
                self.assertEqual(ROLES[name]["tags"], [name])
                gate = expression(ROLES[name]["when"])
                self.assertTrue(gate(selfhosted_selected=[name]))
                self.assertFalse(gate(selfhosted_selected=[other for other in ROLES if other != name]))
        self.assertEqual(ROLES["nas_tailscale"]["tags"], ["tailscale"])
        self.assertTrue(expression(ROLES["nas_tailscale"]["when"])(selfhosted_selected=["tailscale"]))

    def test_docker_runtime_runs_only_for_targeted_selected_services(self):
        runtime = expression(ROLES["docker_runtime"]["when"])
        self.assertEqual(ROLES["docker_runtime"]["tags"], ["always"])
        self.assertTrue(runtime(selfhosted_selected=["audiobookshelf"], ansible_run_tags=["all"]))
        self.assertTrue(runtime(selfhosted_selected=["audiobookshelf"], ansible_run_tags=["audiobookshelf"]))
        self.assertFalse(runtime(selfhosted_selected=["audiobookshelf"], ansible_run_tags=["znc"]))
        self.assertFalse(runtime(selfhosted_selected=[], ansible_run_tags=["all"]))

    def test_selection_flags_must_be_booleans(self):
        cases = [({"caddy_enabled": True, "znc_enabled": False}, True), ({}, True),
                 ({"caddy_enabled": "true"}, False), ({"caddy_enabled": 1}, False),
                 ({"selfhosted_services": {"caddy": {"enabled": True}}}, False)]
        for flags, valid in cases:
            with self.subTest(flags=flags):
                result = run_selection(self.temp.name, flags, VALIDATION)
                self.assertEqual(result.returncode == 0, valid, result.stdout)

    def test_example_selections_are_booleans_and_bouncer_selects_nothing(self):
        names = PLAY["vars"]["selfhosted_service_names"]
        for group in ("nas", "irc_bouncers"):
            settings = group_vars(group)
            with self.subTest(group=group):
                self.assertNotIn("selfhosted_services", settings)
                self.assertEqual(sorted(key for key in settings if key.endswith("_enabled")),
                                 sorted(name + "_enabled" for name in names))
                for name in names:
                    self.assertIsInstance(settings[name + "_enabled"], bool)
        self.assertFalse([key for key in group_vars("all") if key.endswith("_enabled")])
        self.assertEqual(selected(self.temp.name, group_vars("irc_bouncers")), [])


if __name__ == "__main__":
    unittest.main()
