"""Offline checks for Audiobookshelf's validation and generated configuration."""

from pathlib import Path
import tempfile
import unittest

import yaml

from rolefixture import TEMP_ROOT, assert_cases_fail_validation, run_role, validate_task


LIBRARIES = [
    {"name": "audiobooks", "path": "/srv/example media/audio$books"},
    {"name": "podcasts", "path": "/srv/example/podcasts", "read_only": False},
]
SETTINGS = {
    "caddy_enabled": True,
    "audiobookshelf_enabled": True,
    "audiobookshelf_hostname": "audiobooks.example.com",
    "audiobookshelf_libraries": LIBRARIES,
}


class AudiobookshelfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="audiobookshelf-test-", dir=TEMP_ROOT)
        cls.directory = Path(cls.temp.name)
        result = run_role("audiobookshelf", cls.directory, SETTINGS, ("compose.yml",))
        if result.returncode:
            raise AssertionError(result.stdout)
        cls.compose = yaml.safe_load((cls.directory / "compose.yml").read_text())

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_loopback_only_and_unprivileged(self):
        self.assertEqual(self.compose["name"], "selfhosted-audiobookshelf")
        service = self.compose["services"]["audiobookshelf"]
        self.assertEqual(service["image"], "ghcr.io/advplyr/audiobookshelf:2.37.2")
        self.assertEqual(service["network_mode"], "host")
        self.assertNotIn("ports", service)
        self.assertEqual(service["user"], "1000:1000")
        self.assertEqual(service["environment"], {"HOST": "127.0.0.1", "PORT": "13378", "TZ": "UTC"})
        self.assertIn("http://127.0.0.1:13378/healthcheck", service["healthcheck"]["test"][3])

    def test_libraries_are_explicit_bind_mounts(self):
        volumes = self.compose["services"]["audiobookshelf"]["volumes"]
        self.assertEqual(volumes[:2], ["./config:/config", "./metadata:/metadata"])
        self.assertEqual(volumes[2], {
            "type": "bind", "source": "/srv/example media/audio$$books", "target": "/media/audiobooks",
            "read_only": True, "bind": {"create_host_path": False},
        })
        self.assertEqual(volumes[3]["target"], "/media/podcasts")
        self.assertFalse(volumes[3]["read_only"])

    def test_invalid_inputs_fail(self):
        cases = [
            {"caddy_enabled": False},
            {"audiobookshelf_hostname": "Not A Hostname"},
            {"audiobookshelf_port": 80},
            {"audiobookshelf_uid": 0},
            {"audiobookshelf_timezone": "../etc/passwd"},
            {"audiobookshelf_timezone": "UTC\nPORT: 80"},
            {"audiobookshelf_libraries": "/srv/example/audiobooks"},
            {"audiobookshelf_libraries": [LIBRARIES[0], LIBRARIES[0]]},
            {"audiobookshelf_libraries": [{"name": "Audio Books", "path": "/srv/example"}]},
            {"audiobookshelf_libraries": [{"name": "audiobooks"}]},
            {"audiobookshelf_libraries": [{"name": "audiobooks", "path": "/srv/x", "read_only": "no"}]},
        ]
        # Includes sibling service directories, such as Caddy's token, under the deployment root.
        for path in ("relative/path", "/srv/example/", "/srv/../etc", "/srv/./example", "/", "/opt",
                     "/opt/selfhosted", "/opt/selfhosted/caddy", "/opt/selfhosted/audiobookshelf/config",
                     "/srv/bad\npath"):
            cases.append({"audiobookshelf_libraries": [{"name": "audiobooks", "path": path}]})
        assert_cases_fail_validation(self, self.directory, SETTINGS, cases, [validate_task("audiobookshelf")])


if __name__ == "__main__":
    unittest.main()
