"""Parse and verify docker/versions.env, the pinned-version lock file."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

_IMAGE_RE = re.compile(r"^(?P<name>[^:@\s]+):(?P<tag>[^@\s]+)@(?P<digest>sha256:[0-9a-f]{64})$")
_DIGEST_LINE_RE = re.compile(r"^Digest:\s*(sha256:[0-9a-f]{64})\s*$", re.MULTILINE)


@dataclass(frozen=True)
class PinnedImage:
    key: str
    name: str
    tag: str
    digest: str

    @property
    def tag_ref(self) -> str:
        return f"{self.name}:{self.tag}"


def pinned_images(values: dict[str, str]) -> list[PinnedImage]:
    """Every *_IMAGE entry must be pinned by both tag and digest."""
    images = []
    for key, value in values.items():
        if not key.endswith("_IMAGE"):
            continue
        match = _IMAGE_RE.match(value)
        if not match:
            raise ValueError(f"{key} must look like name:tag@sha256:<digest>, got {value!r}")
        images.append(PinnedImage(key, match["name"], match["tag"], match["digest"]))
    return images


def registry_digest(tag_ref: str) -> str:
    """Resolve a tag's current index digest from the registry without pulling the image."""
    result = subprocess.run(
        ["docker", "buildx", "imagetools", "inspect", tag_ref],
        capture_output=True,
        text=True,
        check=True,
    )
    match = _DIGEST_LINE_RE.search(result.stdout)
    if not match:
        raise RuntimeError(f"no digest in registry response for {tag_ref}")
    return match.group(1)


def verify(images: list[PinnedImage]) -> list[str]:
    """Return mismatch messages (empty when every tag still resolves to its pinned digest)."""
    problems = []
    for image in images:
        current = registry_digest(image.tag_ref)
        if current != image.digest:
            problems.append(f"{image.key}: {image.tag_ref} now {current}, lock has {image.digest}")
    return problems
