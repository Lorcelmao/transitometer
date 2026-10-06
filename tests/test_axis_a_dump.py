"""Dumping engine result topics: at-least-once redeliveries collapse, real conflicts fail."""

from __future__ import annotations

import pyarrow as pa
import pytest

from transitometer.axis_a.dump import KEYS, dedupe, to_table

ROW = {
    "grp": "bus",
    "service_date": "20260922",
    "route_id": "B6",
    "stop_id": "S1",
    "window_start": 960,
    "delays": 2,
}


def test_an_exact_redelivery_is_counted_and_dropped() -> None:
    rows, duplicates = dedupe([ROW, dict(ROW), {**ROW, "window_start": 1020}], KEYS["w1"])
    assert len(rows) == 2 and duplicates == 1


def test_two_different_rows_for_one_key_fail() -> None:
    with pytest.raises(ValueError, match="conflicting rows"):
        dedupe([ROW, {**ROW, "delays": 3}], KEYS["w1"])


def test_a_field_the_engine_left_out_becomes_null() -> None:
    schema = pa.schema([("grp", pa.string()), ("stddev_delay_s", pa.float64())])
    table = to_table([{"grp": "bus"}], schema)
    assert table.column("stddev_delay_s").to_pylist() == [None]
