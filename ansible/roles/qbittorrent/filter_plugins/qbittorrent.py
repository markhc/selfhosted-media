"""Filters for the qBittorrent role."""

import base64
import hashlib


def qbittorrent_pbkdf2(password, salt_seed):
    """Return qBittorrent's WebUI Password_PBKDF2 value for PASSWORD.

    qBittorrent uses PBKDF2-HMAC-SHA512 with 100,000 iterations, a 16-byte salt,
    and a 64-byte key. The salt is derived from SALT_SEED instead of random so
    redeployments write the same value and the configuration stays unchanged.
    """
    salt = hashlib.sha256(("selfhosted-qbittorrent:" + salt_seed).encode()).digest()[:16]
    key = hashlib.pbkdf2_hmac("sha512", password.encode(), salt, 100000, 64)
    return "@ByteArray({}:{})".format(base64.b64encode(salt).decode(), base64.b64encode(key).decode())


class FilterModule:
    def filters(self):
        return {"qbittorrent_pbkdf2": qbittorrent_pbkdf2}
