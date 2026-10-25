"""Build a pinned container image reference from its repository, tag, and digest."""

import re

from ansible.errors import AnsibleFilterError


# Docker's distribution reference grammar: an optional registry host, then
# lowercase path components. Like Docker, treat the first component as a host
# only when it is localhost or contains a dot or a port.
_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
_HOST = rf"(?:(?:localhost|{_LABEL}(?:\.{_LABEL})+)(?::[0-9]{{1,5}})?|{_LABEL}:[0-9]{{1,5}})"
_COMPONENT = r"[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*"
REPOSITORY = re.compile(rf"^(?:{_HOST}/)?{_COMPONENT}(?:/{_COMPONENT})*$")
TAG = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")
DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")


def container_image(repository, tag="", digest=""):
    """Return REPOSITORY:TAG, REPOSITORY@DIGEST, or REPOSITORY:TAG@DIGEST.

    A digest pins the exact image; the tag then only documents it. Without a
    digest the tag is required and may not be "latest", so every deployment
    names a specific release.
    """
    for name, value in (("repository", repository), ("tag", tag), ("digest", digest)):
        if not isinstance(value, str):
            raise AnsibleFilterError(f"Container image {name} {value!r} must be a quoted string.")
    if not REPOSITORY.match(repository):
        raise AnsibleFilterError(
            f"Container image repository {repository!r} is not a valid image name, "
            "such as example/app or registry.example.com/example/app.")
    if tag and not TAG.match(tag):
        raise AnsibleFilterError(f"Container image tag {tag!r} for {repository} is not a valid tag.")
    if digest and not DIGEST.match(digest):
        raise AnsibleFilterError(
            f"Container image digest for {repository} must be sha256: followed by 64 lowercase hex digits.")
    if not digest and (not tag or tag == "latest"):
        raise AnsibleFilterError(
            f"Container image {repository} needs a pinned tag other than latest, or a sha256 digest.")
    return repository + (f":{tag}" if tag else "") + (f"@{digest}" if digest else "")


class FilterModule:
    def filters(self):
        return {"container_image": container_image}
