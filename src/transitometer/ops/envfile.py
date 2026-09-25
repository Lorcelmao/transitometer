"""Minimal reader for docker-compose style KEY=VALUE files (versions lock, host config)."""

from __future__ import annotations

from pathlib import Path


def read_env_file(path: Path) -> dict[str, str]:
    """Read KEY=VALUE lines, ignoring blanks and comments; values are taken literally."""
    values: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or not key.strip():
            raise ValueError(f"{path}:{number}: expected KEY=VALUE")
        values[key.strip()] = value.strip()
    return values
