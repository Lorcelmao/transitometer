"""S10 benchmark harness: latency definitions and slice plans (controlled inputs, no engines)."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from transitometer.axis_a.produce import FIELDS
from transitometer.bench import axis_a_latency as lat
from transitometer.bench import axis_a_slice
from transitometer.bench.axis_a import MemorySampler


def _con(**tables: pa.Table) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    for name, table in tables.items():
        con.register(name, table)
    return con


def _passages(arrivals: list[int], appends: list[int], trips: list[str]) -> pa.Table:
    n = len(arrivals)
    return pa.table(
        {
            "grp": ["bus"] * n,
            "service_date": ["20260922"] * n,
            "route_id": ["B1"] * n,
            "stop_id": ["S1"] * n,
            "trip_key": trips,
            "observed_arrival": arrivals,
            "append_ms": appends,
        }
    )


def test_w2_latency_matches_each_headway_to_its_passage_and_skips_warmup() -> None:
    inp = _passages([100, 200, 300], [1_000, 40_000, 50_000], ["a", "b", "c"])
    out = pa.table(
        {
            "grp": ["bus"] * 4,
            "service_date": ["20260922"] * 4,
            "route_id": ["B1"] * 4,
            "stop_id": ["S1"] * 4,
            "trip_key": ["a", "b", "c", "c"],  # c delivered twice: the first append counts
            "append_ms": [2_000, 45_000, 52_000, 59_000],
        }
    )
    con = _con(inp=inp, out=out)
    dist = lat.distribution(con, lat.w2_latencies("inp", "out", warmup_ms=31_000))
    assert dist["samples"] == 2  # passage a is in the warm-up
    assert dist["p50_ms"] == 3_500.0 and dist["max_ms"] == 5_000.0


def test_w1_latency_counts_from_the_first_passage_that_closes_the_window() -> None:
    # Window [0, 60) closes once event time reaches 180 (60 s window + 120 s watermark).
    inp = _passages([10, 120, 179, 180, 400], [0, 1_000, 2_000, 3_000, 4_000], list("abcde"))
    out = pa.table(
        {
            "grp": ["bus", "bus", "bus"],
            "service_date": ["20260922"] * 3,
            "route_id": ["B1"] * 3,
            "stop_id": ["S1"] * 3,
            "window_start": [0, 120, 600],  # 600 is only closed by the end marker: excluded
            "append_ms": [3_500, 4_250, 9_000],
        }
    )
    con = _con(inp=inp, out=out)
    dist = lat.distribution(con, lat.w1_latencies("inp", "out", warmup_ms=0))
    assert dist["samples"] == 2
    assert dist["percentiles_ms"][0] == 250.0  # 120 needs 300: closed by e at 4_000
    assert dist["percentiles_ms"][100] == 500.0  # 0 needs 180: closed by d at 3_000


def _stream(tmp_path: Path, n: int) -> Path:
    start = axis_a_slice.START
    rows: dict[str, list[object]] = {f: [None] * n for f in FIELDS}
    rows.update(
        grp=["bus"] * n,
        service_date=["20260922"] * n,
        route_id=[f"R{i % 3}" for i in range(n)],
        stop_id=[f"S{i % 5}" for i in range(n)],
        service_hour=[7] * n,
        trip_key=[f"T{i}" for i in range(n)],
        trip_id=[f"T{i}" for i in range(n)],
        unit=[f"U{i}" for i in range(n)],
        source=["scheduled"] * n,
        observed_arrival=[start - 50 + 5 * i for i in range(n)],
        delay_s=[i % 7 for i in range(n)],
        ref_headway_s=[600.0] * n,
    )
    path = tmp_path / "passages.parquet"
    pq.write_table(pa.table(rows), path)
    return path


def test_slice_plans_keep_the_data_and_fix_partitions_up_front(tmp_path: Path) -> None:
    passages = _stream(tmp_path, 3000)
    clean = axis_a_slice.prepare(passages, tmp_path / "clean", 2000, "clean")
    late = axis_a_slice.prepare(passages, tmp_path / "late", 2000, "late:30")
    dup = axis_a_slice.prepare(passages, tmp_path / "dup", 2000, "dup")
    assert clean["passages"] == 2000 and clean["faulted_passages"] > 0
    assert clean["messages"] == 2001  # plus the end marker
    assert dup["messages"] == 2001 + dup["faulted_passages"]
    for record, folder in ((clean, "clean"), (late, "late"), (dup, "dup")):
        assert sum(b["end"] for b in record["partitions"].values()) == record["messages"]
        send = pq.read_table(tmp_path / folder / "send.parquet")
        assert set(send.column("partition").to_pylist()) <= set(range(6))
        assert json.loads((tmp_path / folder / "record.json").read_text())["plan"] == record["plan"]
    assert clean["golden_rows"] == late["golden_rows"] == dup["golden_rows"]
    order_clean = pq.read_table(tmp_path / "clean" / "send.parquet").column("trip_key")
    order_late = pq.read_table(tmp_path / "late" / "send.parquet").column("trip_key")
    assert order_clean != order_late
    assert sorted(order_clean.to_pylist()) == sorted(order_late.to_pylist())
    first = pq.read_table(tmp_path / "clean" / "send.parquet").column("observed_arrival")[0]
    assert first.as_py() >= axis_a_slice.START


def test_memory_units_parse_to_gib() -> None:
    assert MemorySampler._gib("512MiB") == 0.5
    assert MemorySampler._gib("2.5GiB") == 2.5
    assert MemorySampler._gib("0B") == 0.0
