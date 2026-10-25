"""Offline checks for service selection in the site playbook."""

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


def selected(services):
    return expression(PLAY["vars"]["selfhosted_selected"])(selfhosted_services=services)


class SiteSelectionTests(unittest.TestCase):
    def test_only_explicitly_enabled_services_are_selected(self):
        self.assertEqual(selected({}), [])
        self.assertEqual(selected({"caddy": {"enabled": True}, "thelounge": {"enabled": False},
                                   "znc": {}, "plex": None}), ["caddy"])

    def test_each_service_role_is_tagged_and_gated_by_its_own_key(self):
        for name in ("caddy", "thelounge", "audiobookshelf", "znc"):
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
        validation = next(task for task in PLAY["pre_tasks"] if task["name"] == "Validate the service selection")
        cases = [({"caddy": {"enabled": True}, "znc": {"enabled": False}, "plex": None}, True),
                 ({}, True), ({"caddy": {"enabled": "true"}}, False), ({"caddy": {"enabled": 1}}, False),
                 (["caddy"], False)]
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            for services, valid in cases:
                with self.subTest(services=services):
                    result = run_play(temp, {"selfhosted_services": services}, [validation])
                    self.assertEqual(result.returncode == 0, valid, result.stdout)

    def test_example_selections_are_booleans_and_bouncer_selects_nothing(self):
        for group in ("nas", "irc_bouncers"):
            settings = yaml.safe_load((ROOT / f"ansible/inventories/example/group_vars/{group}.yml").read_text())
            for service in settings["selfhosted_services"].values():
                self.assertIsInstance(service["enabled"], bool)
        bouncer = yaml.safe_load((ROOT / "ansible/inventories/example/group_vars/irc_bouncers.yml").read_text())
        self.assertFalse(selected(bouncer["selfhosted_services"]))


if __name__ == "__main__":
    unittest.main()
