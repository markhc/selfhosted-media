"""Offline checks for pinned container image references and their documented defaults."""

import importlib.util
import re
import tempfile
import unittest
from pathlib import Path

import yaml
from ansible.errors import AnsibleFilterError

from rolefixture import ROOT, TEMP_ROOT, run_role


SPEC = importlib.util.spec_from_file_location(
    "container_image", ROOT / "ansible/plugins/filter/container_image.py")
FILTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FILTER)
DIGEST = "sha256:" + "0123456789abcdef" * 4
# Image prefix -> role whose defaults define it.
PREFIXES = {"nas_tailscale": "nas_tailscale", "caddy": "caddy", "thelounge": "thelounge",
            "audiobookshelf": "audiobookshelf", "qbittorrent": "qbittorrent", "qui": "qui",
            "autobrr": "autobrr", "prowlarr": "prowlarr", "sonarr": "sonarr", "radarr": "radarr",
            "pihole": "pihole", "node_exporter": "node_exporter", "cadvisor": "cadvisor",
            "prometheus": "prometheus", "loki": "loki", "alloy": "alloy", "grafana": "grafana",
            "znc": "znc",
            "znc_acme": "znc"}


def defaults(role):
    return yaml.safe_load((ROOT / f"ansible/roles/{role}/defaults/main.yml").read_text())


class ContainerImageFilterTests(unittest.TestCase):
    def test_valid_references(self):
        image = FILTER.container_image
        self.assertEqual(image("znc", "1.10.3-slim"), "znc:1.10.3-slim")
        self.assertEqual(image("registry.example.com:5000/mirror/app", "v1.2"),
                         "registry.example.com:5000/mirror/app:v1.2")
        self.assertEqual(image("localhost/app", "1"), "localhost/app:1")
        self.assertEqual(image("Registry.Example.com/app", "1"), "Registry.Example.com/app:1")
        self.assertEqual(image("example/app", "", DIGEST), f"example/app@{DIGEST}")
        self.assertEqual(image("example/app", "1.2", DIGEST), f"example/app:1.2@{DIGEST}")
        self.assertEqual(image("example/app", "latest", DIGEST), f"example/app:latest@{DIGEST}")

    def test_invalid_references_are_refused(self):
        cases = [("Example/app", "1.2", ""), ("example/app", "latest", ""), ("example/app", "", ""),
                 ("example/app", "1 2", ""), ("example/app", "-1.2", ""), ("example/app:1.2", "1.2", ""),
                 ("example/app", "1.2", DIGEST[:-1]), ("example/app", "1.2", DIGEST.upper()),
                 ("example/app", "1.2", "sha512:" + "0" * 128), ("example/app", 5.3, ""),
                 ("example/app\nother", "1.2", ""), ("Registry/app", "1.2", "")]
        for case in cases:
            with self.subTest(case=case):
                with self.assertRaises(AnsibleFilterError):
                    FILTER.container_image(*case)


class ImageDefaultsTests(unittest.TestCase):
    def test_every_default_is_pinned_documented_and_shown_in_the_example_inventory(self):
        documented = re.findall(r"^\| .+? \| `([a-z_]+)` \|$", (ROOT / "docs/operations.md").read_text(), re.MULTILINE)
        self.assertEqual(sorted(documented), sorted(PREFIXES))
        example = {}
        for group in ("nas", "irc_bouncers"):
            example.update(yaml.safe_load(
                (ROOT / f"ansible/inventories/example/group_vars/{group}.yml").read_text()))
        for prefix, role in PREFIXES.items():
            with self.subTest(prefix=prefix):
                settings = defaults(role)
                tag_key = "caddy_version" if prefix == "caddy" else f"{prefix}_image_tag"
                self.assertIsInstance(settings[tag_key], str)
                self.assertEqual(settings[f"{prefix}_image_digest"], "")
                FILTER.container_image(settings[f"{prefix}_image_repository"], settings[tag_key])
                for key in (f"{prefix}_image_repository", tag_key):
                    self.assertEqual(example[key], settings[key], key)
        self.assertEqual(example["caddy_cloudflare_version"], defaults("caddy")["caddy_cloudflare_version"])

    def test_roles_render_the_overridden_image(self):
        import test_qbittorrent

        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            variables = {**test_qbittorrent.SETTINGS, "qbittorrent_image_repository": "registry.example.com/mirror/qbt",
                         "qbittorrent_image_tag": "5.3.1-1", "qbittorrent_image_digest": DIGEST}
            result = run_role("qbittorrent", temp, variables, ("compose.yml",))
            self.assertEqual(result.returncode, 0, result.stdout)
            compose = yaml.safe_load((Path(temp) / "compose.yml").read_text())
            self.assertEqual(compose["services"]["qbittorrent"]["image"], f"registry.example.com/mirror/qbt:5.3.1-1@{DIGEST}")
            result = run_role("qbittorrent", temp, {**test_qbittorrent.SETTINGS, "qbittorrent_image_tag": "latest"})
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("needs a pinned tag other than latest", result.stdout)

    def test_caddy_build_uses_the_configured_base_images(self):
        import test_caddy

        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            variables = {**test_caddy.SETTINGS, "caddy_image_repository": "registry.example.com/mirror/caddy",
                         "caddy_image_digest": DIGEST}
            result = run_role("caddy", temp, variables, ("Dockerfile",))
            self.assertEqual(result.returncode, 0, result.stdout)
            dockerfile = (Path(temp) / "Dockerfile").read_text()
            self.assertIn("FROM registry.example.com/mirror/caddy:2.11.7-builder AS builder", dockerfile)
            self.assertIn(f"FROM registry.example.com/mirror/caddy:2.11.7@{DIGEST}", dockerfile)
            self.assertIn("xcaddy build v2.11.7 ", dockerfile)
            for extra in ({"caddy_version": "2.11.7; rm -rf /"}, {"caddy_cloudflare_version": "0.2.4"}):
                with self.subTest(extra=extra):
                    result = run_role("caddy", temp, {**test_caddy.SETTINGS, **extra})
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertIn("Set caddy_version", result.stdout)


if __name__ == "__main__":
    unittest.main()
