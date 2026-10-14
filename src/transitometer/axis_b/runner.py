"""Run the suite on one Axis B arm: every statement once, answers as Parquet, a JSON record.

The arm supplies `execute(sql) -> pyarrow.Table`. The wall time covers the query and the transfer
of its full answer into Arrow (what an application would wait for), not the Parquet write. One run
per query: these times are informational; S10 owns cold/warm repeats and percentiles.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from transitometer.axis_b import dialect


def run_suite(
    engine: str,
    execute: Callable[[str], pa.Table],
    time_travel: str | None,
    out_dir: Path,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.parquet"):  # a query that fails leaves no earlier answer
        stale.unlink()
    queries: dict[str, Any] = {}
    for statement in dialect.statements(engine, time_travel):
        if statement.sql is None:
            queries[statement.name] = {"applicable": False, "reason": statement.reason}
            continue
        print(f"progress axis-b {engine} {statement.name}", file=sys.stderr, flush=True)
        started = time.perf_counter()
        answer = execute(statement.sql)
        seconds = time.perf_counter() - started
        pq.write_table(answer, out_dir / f"{statement.name}.parquet", compression="zstd")
        queries[statement.name] = {
            "applicable": True,
            "rows": answer.num_rows,
            "seconds": round(seconds, 3),
            "adaptations": list(statement.adaptations),
        }
    return {"engine": engine, "answers": str(out_dir), "queries": queries}
