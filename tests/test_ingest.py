"""Fetch + validate against a tiny fake gtfsrt.io archive served over file:// URLs."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from pathlib import Path
from urllib.parse import unquote

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from transitometer.ingest.fetch import download, fetch_all, load_manifest
from transitometer.ingest.sources import (
    DateRange,
    RealtimeFeed,
    ScheduleVersion,
    Sources,
    b64url,
    load_sources,
)
from transitometer.ingest.validate import validate

ROOT = Path(__file__).resolve().parents[1]
BUS_URL = "https://example.test/bus/tripUpdates"
SUB_URL = "https://example.test/subway"
DAYS = [date(2026, 9, 22), date(2026, 9, 23)]  # service days (Tue, Wed)
SPILL = date(2026, 9, 24)  # next UTC partition, fetched to complete the last service day
TABLES = ("calendar.parquet", "calendar_dates.parquet", "trips.parquet")


def _local(key: str) -> str:
    """Archive keys contain ':' (digests), which Windows paths cannot hold."""
    return key.replace(":", "_")


def downloader_for(sources: Sources, base: Path) -> Callable[[str, Path], str]:
    """Map archive URLs to the fake archive, then download through the real code over file://."""

    def fetch(url: str, dest: Path) -> str:
        key = unquote(url.removeprefix(sources.archive_base_url + "/"))
        return download((base / _local(key)).as_uri(), dest, retries=0)

    return fetch


def _write(path: Path, rows: Mapping[str, Sequence[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(rows), path)


def _trip_updates(trip_ids: list[str], timestamps: list[int]) -> dict[str, Sequence[object]]:
    n = len(trip_ids)
    return {
        "source_file": [f"snap-{t}.pb" for t in timestamps],
        "feed_timestamp": timestamps,
        "entity_id": [f"e{i}" for i in range(n)],
        "trip_id": trip_ids,
        "route_id": ["R1"] * n,
        "start_date": ["20260922"] * n,
        "stop_sequence": [1] * n,
        "stop_id": ["S1"] * n,
        "arrival_time": timestamps,
        "departure_time": timestamps,
    }


def _schedule(base: Path, url: str, digest: str, trip_ids: list[str]) -> None:
    folder = base / _local(f"schedules/base64url={b64url(url)}/_feed_digest={digest}")
    _write(
        folder / "calendar.parquet",
        {
            "service_id": ["WKD"],
            "monday": [1],
            "tuesday": [1],
            "wednesday": [1],
            "thursday": [1],
            "friday": [1],
            "saturday": [0],
            "sunday": [0],
            "start_date": ["20260901"],
            "end_date": ["20261231"],
        },
    )
    _write(
        folder / "calendar_dates.parquet",
        {"service_id": ["WKD"], "date": ["20261225"], "exception_type": [2]},
    )
    _write(folder / "trips.parquet", {"trip_id": trip_ids, "service_id": ["WKD"] * len(trip_ids)})


@pytest.fixture
def archive(tmp_path: Path) -> tuple[Sources, Path]:
    base = tmp_path / "archive"
    t0 = 1_790_000_000
    for day in DAYS:
        # Bus: exact trip_id match; 20-minute snapshot gap on the second day.
        gap = 1200 if day == DAYS[1] else 30
        _write(
            base / f"trip_updates/date={day}/base64url={b64url(BUS_URL)}/data.parquet",
            _trip_updates(["B1", "B2", "B3"], [t0, t0 + 30, t0 + 30 + gap]),
        )
        # Subway: real-time ids are the static id after its first "_".
        _write(
            base / f"trip_updates/date={day}/base64url={b64url(SUB_URL)}/data.parquet",
            _trip_updates(["083250_1..S03R", "090000_2..N01R"], [t0, t0 + 30]),
        )
    # UTC spill-over partition: late bus trip; a 7-line-style id without a path code.
    _write(
        base / f"trip_updates/date={SPILL}/base64url={b64url(BUS_URL)}/data.parquet",
        _trip_updates(["B3"], [t0]),
    )
    _write(
        base / f"trip_updates/date={SPILL}/base64url={b64url(SUB_URL)}/data.parquet",
        _trip_updates(["118250_7..N"], [t0]),
    )
    _schedule(base, "bus.zip", "v1:" + "a" * 64, ["B1", "B2", "B3"])
    _schedule(
        base,
        "sub.zip",
        "v1:" + "b" * 64,
        [
            "AFA23GEN-1038-Weekday-00_083250_1..S03R",
            "AFA23GEN-1038-Weekday-00_090000_2..N01R",
            "AFA23GEN-1038-Weekday-00_118250_7..N35R",
        ],
    )
    window = DateRange(DAYS[0], DAYS[1])
    lic = "test licence"
    sources = Sources(
        archive_base_url=base.as_uri(),
        window=window,
        golden_window=window,
        realtime=(
            RealtimeFeed("bus", "trip_updates", BUS_URL, "bus", lic),
            RealtimeFeed("sub", "trip_updates", SUB_URL, "subway", lic),
        ),
        schedules=(
            ScheduleVersion(
                "bus_sched",
                "bus",
                "bus.zip",
                "v1:" + "a" * 64,
                date(2026, 9, 1),
                date(2026, 12, 31),
                lic,
            ),
            ScheduleVersion(
                "sub_sched",
                "subway",
                "sub.zip",
                "v1:" + "b" * 64,
                date(2026, 9, 1),
                date(2026, 12, 31),
                lic,
            ),
        ),
        schedule_tables=TABLES,
    )
    return sources, tmp_path


def test_committed_sources_expand_to_expected_files() -> None:
    sources = load_sources(ROOT / "config" / "sources.json")
    files = sources.files()
    days = len(sources.window.days())
    assert days == 7
    partitions = sources.realtime_partitions()
    assert len(partitions) == days + 1 and partitions[-1] > sources.window.end
    assert len(files) == len(sources.realtime) * len(partitions) + len(sources.schedules) * len(
        sources.schedule_tables
    )
    assert len({f.relpath for f in files}) == len(files)
    assert all(f.url.startswith("https://storage.googleapis.com/parquet.gtfsrt.io/") for f in files)


def test_sources_reject_golden_window_outside_window(tmp_path: Path) -> None:
    raw = json.loads((ROOT / "config" / "sources.json").read_text(encoding="utf-8"))
    raw["golden_window"] = {"start": "2026-09-01", "end": "2026-09-02"}
    bad = tmp_path / "sources.json"
    bad.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="golden_window"):
        load_sources(bad)


def test_sources_reject_unknown_feed_type(tmp_path: Path) -> None:
    raw = json.loads((ROOT / "config" / "sources.json").read_text(encoding="utf-8"))
    raw["realtime"][0]["feed_type"] = "service_alerts_v2"
    bad = tmp_path / "sources.json"
    bad.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown feed_type"):
        load_sources(bad)


def test_fetch_requires_a_worker(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="workers"):
        fetch_all([], tmp_path, tmp_path / "m.json", workers=0)


def test_fetch_records_manifest_and_skips_unchanged(archive: tuple[Sources, Path]) -> None:
    sources, tmp = archive
    dl = downloader_for(sources, tmp / "archive")
    landing, manifest = tmp / "landing", tmp / "data-manifest.json"
    first = fetch_all(
        sources.files(), landing, manifest, workers=2, progress=lambda _: None, downloader=dl
    )
    assert first.ok and len(first.downloaded) == len(sources.files())
    entries = load_manifest(manifest)
    bus_day = "realtime/trip_updates/date=2026-09-22/feed=bus/data.parquet"
    assert entries[bus_day].rows == 3 and len(entries[bus_day].sha256) == 64

    second = fetch_all(
        sources.files(), landing, manifest, workers=2, progress=lambda _: None, downloader=dl
    )
    assert second.ok and second.downloaded == [] and len(second.skipped) == len(sources.files())


def test_fetch_refuses_silent_upstream_change(archive: tuple[Sources, Path]) -> None:
    sources, tmp = archive
    dl = downloader_for(sources, tmp / "archive")
    landing, manifest = tmp / "landing", tmp / "data-manifest.json"
    fetch_all(sources.files(), landing, manifest, progress=lambda _: None, downloader=dl)
    # Upstream content changes while the local copy is damaged (forcing a re-download).
    spec = sources.files()[0]
    key = unquote(spec.url.removeprefix(sources.archive_base_url + "/"))
    _write(tmp / "archive" / _local(key), _trip_updates(["B9"], [1]))
    local = landing / spec.relpath
    local.write_bytes(b"damaged")

    changed = fetch_all([spec], landing, manifest, progress=lambda _: None, downloader=dl)
    assert (
        spec.relpath in changed.errors
        and "upstream content changed" in changed.errors[spec.relpath]
    )
    # A refused change must not replace the landing file or leave temporary files behind.
    assert local.read_bytes() == b"damaged"
    assert sorted(p.name for p in local.parent.iterdir()) == ["data.parquet"]
    adopted = fetch_all(
        [spec], landing, manifest, accept_changes=True, progress=lambda _: None, downloader=dl
    )
    assert adopted.ok and load_manifest(manifest)[spec.relpath].rows == 1


def test_fetch_reports_missing_source(archive: tuple[Sources, Path]) -> None:
    sources, tmp = archive
    dl = downloader_for(sources, tmp / "archive")
    spec = sources.files()[0]
    missing = type(spec)(spec.url + ".nope", spec.relpath, spec.kind, spec.source, spec.license)
    result = fetch_all(
        [missing], tmp / "landing", tmp / "m.json", progress=lambda _: None, downloader=dl
    )
    assert not result.ok and spec.relpath in result.errors


def test_validate_measures_coverage_matching_and_gaps(archive: tuple[Sources, Path]) -> None:
    sources, tmp = archive
    dl = downloader_for(sources, tmp / "archive")
    landing, manifest = tmp / "landing", tmp / "data-manifest.json"
    fetch_all(sources.files(), landing, manifest, progress=lambda _: None, downloader=dl)
    report = validate(sources, landing, load_manifest(manifest))

    assert report.ok, report.failures
    assert report.service_coverage["bus_sched"] == {"2026-09-22": 1, "2026-09-23": 1}
    matches = {m["feed"]: m for m in report.trip_matching}
    assert matches["bus"]["exact_match"] == 3 and matches["bus"]["match_ratio"] == 1.0
    sub = matches["sub"]
    assert (sub["golden_trip_ids"], sub["exact_match"], sub["suffix_match"]) == (3, 0, 2)
    assert sub["route_direction_match"] == 3 and sub["match_ratio"] == 1.0
    assert any("snapshot gap 20 min" in w for w in report.warnings)
    assert report.totals["realtime_rows"] == 2 * (3 + 2) + (1 + 1)
    assert {d["utc_partition"] for d in report.realtime_days} == {
        "2026-09-22",
        "2026-09-23",
        "2026-09-24",
    }


def test_validate_applies_calendar_date_additions_and_removals(
    archive: tuple[Sources, Path],
) -> None:
    sources, tmp = archive
    dl = downloader_for(sources, tmp / "archive")
    bus_dates = (
        tmp
        / "archive"
        / _local(f"schedules/base64url={b64url('bus.zip')}/_feed_digest=v1:{'a' * 64}")
    )
    _write(
        bus_dates / "calendar_dates.parquet",
        {
            "service_id": ["EXTRA", "WKD"],
            "date": ["20260922", "20260923"],
            "exception_type": [1, 2],
        },
    )
    landing, manifest = tmp / "landing", tmp / "data-manifest.json"
    fetch_all(sources.files(), landing, manifest, progress=lambda _: None, downloader=dl)
    report = validate(sources, landing, load_manifest(manifest))
    assert report.service_coverage["bus_sched"] == {"2026-09-22": 2, "2026-09-23": 0}
    assert "schedule bus_sched: no active service on 2026-09-23" in report.failures


def test_validate_fails_on_truncated_file(archive: tuple[Sources, Path]) -> None:
    sources, tmp = archive
    dl = downloader_for(sources, tmp / "archive")
    landing, manifest = tmp / "landing", tmp / "data-manifest.json"
    fetch_all(sources.files(), landing, manifest, progress=lambda _: None, downloader=dl)
    victim = landing / sources.files()[0].relpath
    victim.write_bytes(victim.read_bytes()[:10])
    report = validate(sources, landing, load_manifest(manifest))
    assert not report.ok and any("size mismatch" in f for f in report.failures)
