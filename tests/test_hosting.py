"""The hosted app depends only on the repository: pinned like the image, no local paths."""

from __future__ import annotations

import re
import sys

import pytest

from transitometer.serve import kpis

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10 (the Spark image) has no tomllib
    tomllib = None

HOSTED = kpis.REPO / "src" / "transitometer" / "app" / "requirements.txt"
# Absolute host or container paths that must never reach a public file.
LOCAL_PATH = re.compile(r"[A-Za-z]:[\\/]|/data/|/opt/|\\Users\\|/home/")


def _pins(lines: list[str]) -> set[str]:
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


@pytest.mark.skipif(tomllib is None, reason="tomllib needs Python 3.11+")
def test_hosted_requirements_equal_the_app_extra_and_the_duckdb_pin() -> None:
    assert tomllib is not None
    project = tomllib.loads((kpis.REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    duckdb = {d for d in project["dependencies"] if d.startswith("duckdb==")}
    expected = set(project["optional-dependencies"]["app"]) | duckdb
    assert _pins(HOSTED.read_text(encoding="utf-8").splitlines()) == expected


def test_the_snapshot_contains_no_local_paths() -> None:
    folder = kpis.SNAPSHOT_DIR
    if not (folder / "manifest.json").exists():
        pytest.skip("no snapshot in showcase/data yet (python tasks.py snapshot)")
    for path in [folder / "manifest.json", *sorted((folder / "evidence").glob("*.json"))]:
        found = LOCAL_PATH.findall(path.read_text(encoding="utf-8"))
        assert not found, f"{path.name} contains local paths: {found[:3]}"
