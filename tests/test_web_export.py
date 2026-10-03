"""The Next.js site's JSON: deterministic, complete, enveloped, from a validated snapshot only."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from transitometer.serve import kpis, views, web_export

SNAPSHOT = kpis.SNAPSHOT_DIR
pytestmark = pytest.mark.skipif(
    not (SNAPSHOT / "manifest.json").exists(), reason="no snapshot in showcase/data yet"
)
MAX_BYTES = 40_000_000  # far below Vercel's 100 MB upload limit; keeps the repository light


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, object]]:
    out = tmp_path_factory.mktemp("web")
    parity = web_export.build(SNAPSHOT, out / "data", out / "evidence")
    return out, parity


def _files(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_two_builds_are_byte_identical(
    built: tuple[Path, dict[str, object]], tmp_path: Path
) -> None:
    out, parity = built
    again = web_export.build(SNAPSHOT, tmp_path / "data", tmp_path / "evidence")
    assert _files(out / "data") == _files(tmp_path / "data")
    assert parity == again


def test_every_file_carries_the_envelope_and_its_snapshot(
    built: tuple[Path, dict[str, object]],
) -> None:
    out, _ = built
    manifest = json.loads((SNAPSHOT / "manifest.json").read_text(encoding="utf-8"))
    for path in (out / "data").rglob("*.json"):
        body = json.loads(path.read_text(encoding="utf-8"))
        assert body["schema"] == web_export.SCHEMA
        assert body["source"]["snapshot_commit"] == manifest["validated_commit"]
        assert set(body["source"]["tables"]) <= set(manifest["tables"])


def test_every_page_and_filter_combination_is_exported(
    built: tuple[Path, dict[str, object]],
) -> None:
    out, _ = built
    data = out / "data"
    days = json.loads((SNAPSHOT / "manifest.json").read_text(encoding="utf-8"))["service_dates"]
    for grp in views.GROUPS:
        for page in ("on-time", "headways", "missing-trips", "delay"):
            for day in days:
                assert (data / page / f"{grp}-{day}.json").exists()
        for path in (
            "scorecards/{}.json",
            "early-warning/{}.json",
            "delay/{}-segments.json",
            "map/{}.json",
        ):
            assert (data / path.format(grp)).exists()
        index = json.loads((data / "stops" / grp / "index.json").read_text(encoding="utf-8"))
        assert index["data"]["routes"]
        for route in index["data"]["routes"]:
            assert (data / "stops" / grp / route["file"]).exists()
    for name in ("meta.json", "overview.json", "feed-health.json", "validation.json"):
        assert (data / name).exists()
    assert sorted(p.name for p in (out / "evidence").iterdir()) == sorted(
        json.loads((SNAPSHOT / "manifest.json").read_text(encoding="utf-8"))["evidence"]
    )


def test_the_output_stays_small(built: tuple[Path, dict[str, object]]) -> None:
    out, _ = built
    assert sum(len(b) for b in _files(out / "data").values()) < MAX_BYTES


def test_parity_lists_every_headline_of_every_mode_and_day(
    built: tuple[Path, dict[str, object]],
) -> None:
    _, parity = built
    for grp in views.GROUPS:
        for day in ("20260922", "20260923"):
            figures = parity[f"overview/{grp}/{day}"]
            assert [f["key"] for f in figures] == [  # type: ignore[attr-defined]
                "on_time",
                "bunched",
                "not_delivered",
                "feed_score",
            ]
        assert f"scorecards/{grp}" in parity and f"early-warning/{grp}" in parity


def test_only_a_validated_spark_snapshot_is_published(tmp_path: Path) -> None:
    with pytest.raises(web_export.ExportError, match="no snapshot"):
        web_export.build(tmp_path, tmp_path / "data", tmp_path / "evidence")
    fake = tmp_path / "snapshot"
    shutil.copytree(SNAPSHOT, fake)
    manifest = json.loads((fake / "manifest.json").read_text(encoding="utf-8"))
    manifest["validation"]["ok"] = False
    (fake / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(web_export.ExportError, match="not a validated"):
        web_export.build(fake, tmp_path / "data", tmp_path / "evidence")
    assert not (tmp_path / "data").exists()


def test_route_files_are_url_safe_and_distinct() -> None:
    names = ["M15", "M15+", "M15_2b", "BX12+", "S79-SBS"]
    files = [web_export.route_file(n) for n in names]
    assert len(set(files)) == len(files)
    assert all(f.replace("_", "").replace("-", "").isalnum() for f in files)


def test_the_committed_web_data_matches_the_snapshot() -> None:
    assert web_export.check() == []
