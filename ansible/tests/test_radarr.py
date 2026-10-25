"""Offline checks for Radarr's validation and generated configuration."""

import unittest

from test_sonarr import ArrChecks


class RadarrTests(ArrChecks, unittest.TestCase):
    APP = "radarr"
    PORT = 7878
    IMAGE = "ghcr.io/hotio/radarr:release-6.4.4.10685"
    INSTANCES = [
        {"name": "hd", "address": "127.10.2.1", "hostname": "radarr.example.com"},
        {"name": "uhd", "address": "127.10.2.2", "hostname": "radarr-uhd.example.com"},
    ]
    API_KEYS = {"hd": "00112233445566778899aabbccddeeff", "uhd": "ffeeddccbbaa99887766554433221100"}


if __name__ == "__main__":
    unittest.main()
