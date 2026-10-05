"""Axis A golden reference: the passage stream both engines read, and W1/W2 computed from it.

Runs golden steps 01-05 (everything the BR2 headway rule needs), then three Axis A steps over
their intermediate tables:
  axis_a_passages.sql   the passage stream, enriched with static values only
  axis_a_w1.sql         W1, 1-minute event-time windows of arrival delay per (route, stop)
  axis_a_w2.sql         W2, the BR2 headway rule over the passages

Completeness gate: W2 must equal the frozen golden `headways` table. The headway chain runs through
every passage, so a missing, extra or altered passage changes some headway and fails the gate.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb
import pyarrow.parquet as pq

from transitometer.golden import compare
from transitometer.golden.runner import SQL_STEPS, Params, _inputs, render
from transitometer.ingest.sources import Sources

BR2_STEPS = SQL_STEPS[:5]  # 01_schedule .. 05_headways
AXIS_A_STEPS = ("axis_a_passages.sql", "axis_a_w1.sql", "axis_a_w2.sql")

# Event-time order, ties broken by key then trip: the order the producer sends.
PASSAGE_ORDER = "observed_arrival, grp, service_date, route_id, stop_id, trip_key"
OUTPUTS = {
    "passages": ("axis_a_passages", PASSAGE_ORDER),
    "w1": ("axis_a_w1", "ALL"),
    "w2": ("axis_a_w2", "ALL"),
}


@dataclass
class AxisAGolden:
    out_dir: Path
    row_counts: dict[str, int] = field(default_factory=dict)
    checksums: dict[str, str] = field(default_factory=dict)
    step_seconds: dict[str, float] = field(default_factory=dict)


def run(
    sources: Sources,
    landing: Path,
    out_dir: Path,
    params: Params | None = None,
    memory_limit: str = "14GB",
    threads: int = 8,
    log: Callable[[str], None] = lambda _: None,
) -> AxisAGolden:
    """Write passages.parquet, w1.parquet and w2.parquet to out_dir."""
    params = params or Params()
    out_dir.mkdir(parents=True, exist_ok=True)
    values: dict[str, Any] = {**_inputs(sources, landing), **vars(params)}
    result = AxisAGolden(out_dir)
    with duckdb.connect() as con:
        con.execute(f"SET memory_limit = '{memory_limit}'")
        con.execute(f"SET temp_directory = '{(out_dir / 'tmp').as_posix()}'")
        con.execute("SET preserve_insertion_order = false")
        con.execute(f"SET threads = {threads}")
        for step in (*BR2_STEPS, *AXIS_A_STEPS):
            log(f"{step} started")
            started = time.perf_counter()
            con.execute(render(step, values))
            result.step_seconds[step] = round(time.perf_counter() - started, 1)
            log(f"{step} done in {result.step_seconds[step]:.0f}s")
        for name, (table, order) in OUTPUTS.items():
            target = out_dir / f"{name}.parquet"
            con.execute(
                f"COPY (SELECT * FROM {table} ORDER BY {order}) TO '{target.as_posix()}' "
                "(FORMAT parquet, COMPRESSION zstd)"
            )
            count = con.execute(f"SELECT count(*) FROM {table}").fetchone()
            result.row_counts[name] = int(count[0]) if count else 0
            result.checksums[target.name] = hashlib.sha256(target.read_bytes()).hexdigest()
    return result


def completeness_gate(out_dir: Path, golden_dir: Path, policy: compare.Policy) -> compare.TableDiff:
    """W2 from the passages against the frozen golden headways (same keys and tolerances)."""
    expected = pq.read_table(golden_dir / "headways.parquet")
    actual = pq.read_table(out_dir / "w2.parquet")
    tolerance = {c: policy.tolerance("headways", c) for c in expected.column_names}
    return compare.compare("headways", expected, actual, policy.keys("headways"), tolerance)
