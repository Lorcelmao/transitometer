"""Run the suite on one Axis B arm: every statement, answers as Parquet, a JSON record.

The arm supplies `execute(sql) -> pyarrow.Table`. The wall time covers the query and the transfer
of its full answer into Arrow (what an application would wait for), not the Parquet write.

`passes` runs the whole suite that many times in a row: pass 1 is the cold pass (the first
execution in a fresh engine process) and writes the answers; later passes are warm and only
timed. Every time is kept, in pass order, under `timings`.
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
    passes: int = 1,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.parquet"):  # a query that fails leaves no earlier answer
        stale.unlink()
    statements = dialect.statements(engine, time_travel)
    queries: dict[str, Any] = {}
    timings: dict[str, list[float]] = {}
    for done in range(passes):
        for statement in statements:
            if statement.sql is None:
                queries[statement.name] = {"applicable": False, "reason": statement.reason}
                continue
            print(
                f"progress axis-b {engine} pass {done + 1}/{passes} {statement.name}",
                file=sys.stderr,
                flush=True,
            )
            started = time.perf_counter()
            answer = execute(statement.sql)
            seconds = time.perf_counter() - started
            timings.setdefault(statement.name, []).append(round(seconds, 4))
            if done == 0:
                pq.write_table(answer, out_dir / f"{statement.name}.parquet", compression="zstd")
                queries[statement.name] = {
                    "applicable": True,
                    "rows": answer.num_rows,
                    "seconds": round(seconds, 3),
                    "adaptations": list(statement.adaptations),
                }
    return {
        "engine": engine,
        "answers": str(out_dir),
        "passes": passes,
        "queries": queries,
        "timings": timings,
    }
