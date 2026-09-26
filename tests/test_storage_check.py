from __future__ import annotations

import csv
from pathlib import Path

import pytest

from transitometer.ops.storage_check import (
    GB,
    Status,
    Thresholds,
    append_log,
    build_report,
    classify,
    parse_buildx_private,
    parse_size,
    parse_system_df,
)

# Real `docker system df --format '{{json .}}'` shape (values from this host, 2026-09-24).
DF_OUTPUT = """\
{"Active":"9","Reclaimable":"11.64GB (78%)","Size":"14.84GB","TotalCount":"17","Type":"Images"}
{"Active":"4","Reclaimable":"1.896MB (4%)","Size":"43.86MB","TotalCount":"10","Type":"Containers"}
{"Active":"6","Reclaimable":"821.7MB","Size":"1.756GB","TotalCount":"18","Type":"Local Volumes"}
{"Active":"0","Reclaimable":"3.079GB","Size":"8.122GB","TotalCount":"166","Type":"Build Cache"}
"""


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0B", 0),
        ("512B", 512),
        ("4.1kB", 4_100),
        ("43.86MB", 43_860_000),
        ("1.756GB", 1_756_000_000),
        ("2TB", 2 * 10**12),
    ],
)
def test_parse_size_uses_decimal_units(text: str, expected: int) -> None:
    assert parse_size(text) == expected


@pytest.mark.parametrize("text", ["", "12", "1.5 XB", "GB"])
def test_parse_size_rejects_garbage(text: str) -> None:
    with pytest.raises(ValueError):
        parse_size(text)


def test_parse_system_df_sums_all_types() -> None:
    usage = parse_system_df(DF_OUTPUT)
    assert set(usage) == {"Images", "Containers", "Local Volumes", "Build Cache"}
    assert sum(usage.values()) == 14_840_000_000 + 43_860_000 + 1_756_000_000 + 8_122_000_000


def test_parse_system_df_empty_engine() -> None:
    assert parse_system_df("") == {}


@pytest.mark.parametrize(
    ("gb", "status"),
    [
        (0, Status.OK),
        (24.99, Status.OK),
        (25, Status.WARN),
        (29.99, Status.WARN),
        (30, Status.BLOCK),
    ],
)
def test_classify_threshold_edges(gb: float, status: Status) -> None:
    assert classify(int(gb * GB), Thresholds()) is status


def test_thresholds_must_be_ordered() -> None:
    with pytest.raises(ValueError):
        Thresholds(warn_gb=30, block_gb=25)


def test_compaction_advised_only_when_image_far_above_live_usage() -> None:
    limits = Thresholds()
    bloated = build_report({"Images": 5 * GB}, vhdx_bytes=35 * GB, thresholds=limits)
    healthy = build_report({"Images": 5 * GB}, vhdx_bytes=8 * GB, thresholds=limits)
    busy = build_report({"Images": 27 * GB}, vhdx_bytes=35 * GB, thresholds=limits)
    unknown = build_report({"Images": 5 * GB}, vhdx_bytes=None, thresholds=limits)
    assert bloated.compaction_advised
    assert not healthy.compaction_advised
    assert not busy.compaction_advised
    assert not unknown.compaction_advised


def test_append_log_writes_header_once(tmp_path: Path) -> None:
    log = tmp_path / "results" / "storage-log.csv"
    report = build_report({"Images": 2 * GB}, vhdx_bytes=3 * GB, thresholds=Thresholds())
    append_log(report, log)
    append_log(report, log)
    rows = list(csv.reader(log.open(encoding="utf-8")))
    assert rows[0] == ["timestamp_utc", "type", "bytes"]
    assert [r[1] for r in rows[1:]] == ["Images", "total", "disk_image"] * 2


def test_parse_buildx_private_reads_unshared_bytes() -> None:
    text = "ID  RECLAIMABLE  SIZE\n...\nShared:\t\t3.278GB\nPrivate:\t86.02kB\nTotal:\t\t3.278GB\n"
    assert parse_buildx_private(text) == 86_020
    assert parse_buildx_private("no summary here") is None
