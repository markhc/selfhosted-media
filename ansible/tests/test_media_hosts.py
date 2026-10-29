"""Offline checks for the media service name and loopback address map."""

import json
import re
import tempfile
import unittest

from rolefixture import TEMP_ROOT, assert_cases_fail_validation, run_play


SETTINGS = {
    "qbittorrent_enabled": True,
    "autobrr_enabled": True,
    "prowlarr_enabled": True,
    "sonarr_enabled": True,
    "radarr_enabled": True,
    "plex_enabled": True,
    "sonarr_instances": [{"name": "tv", "address": "127.10.1.1"}, {"name": "anime", "address": "127.10.1.2"}],
    "radarr_instances": [{"name": "hd", "address": "127.10.2.1"}, {"name": "uhd", "address": "127.10.2.2"}],
}
TASKS = [
    {"name": "Resolve fixture", "ansible.builtin.include_role": {"name": "media_hosts"}},
    {"name": "Show fixture", "ansible.builtin.debug": {"msg": "MAP={{ media_hosts_addresses | to_json }}"}},
]


def resolve(directory, variables):
    result = run_play(directory, variables, TASKS)
    match = re.search(r'"MAP=(.*)"$', result.stdout, re.MULTILINE)
    return result, json.loads(match.group(1).replace('\\"', '"')) if match else None


class MediaHostsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="media-hosts-test-", dir=TEMP_ROOT)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_selected_services_and_instances_get_names(self):
        result, addresses = resolve(self.temp.name, SETTINGS)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(addresses, {
            "qbittorrent": "127.10.0.1", "autobrr": "127.10.0.4", "prowlarr": "127.10.0.3", "plex": "127.10.0.5",
            "sonarr-tv": "127.10.1.1",
            "sonarr-anime": "127.10.1.2", "radarr-hd": "127.10.2.1", "radarr-uhd": "127.10.2.2"})

    def test_unselected_services_are_left_out(self):
        result, addresses = resolve(self.temp.name, {**SETTINGS, "radarr_enabled": False, "prowlarr_enabled": False,
                                                     "autobrr_enabled": False, "plex_enabled": False,
                                                     "qui_enabled": True,
                                                     "qui_address": "127.10.0.20"})
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(addresses, {"qbittorrent": "127.10.0.1", "qui": "127.10.0.20",
                                     "sonarr-tv": "127.10.1.1", "sonarr-anime": "127.10.1.2"})
        result, addresses = resolve(self.temp.name, {"caddy_enabled": True})
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(addresses, {})

    def test_invalid_maps_fail(self):
        tv = {"name": "tv", "address": "127.10.1.1"}
        cases = [{"sonarr_instances": "tv"}, {"sonarr_instances": {"tv": "127.10.1.1"}},
                 {"sonarr_instances": ["tv"]}, {"sonarr_instances": [{"name": "tv"}]},
                 {"sonarr_instances": [tv, tv]}, {"sonarr_instances": [{"name": "TV", "address": "127.10.1.1"}]},
                 {"sonarr_instances": [{"name": "tv-", "address": "127.10.1.1"}]},
                 {"sonarr_instances": [tv, {"name": "anime", "address": "127.10.1.1"}]},
                 {"radarr_instances": [{"name": "hd", "address": "127.10.0.1"}]}]
        for address in ("127.0.0.1", "127.0.0.53", "127.0.1.1", "10.0.0.1", "127.10.1", "127.10.1.256",
                        "127.10.01.1", "localhost", 127):
            cases.append({"qbittorrent_address": address})
        assert_cases_fail_validation(self, self.temp.name, SETTINGS, cases, TASKS)


if __name__ == "__main__":
    unittest.main()
