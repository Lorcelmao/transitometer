"""Axis B benchmark steps for DuckDB (python3 -m in the tooling container), and the shared
freshness query.

  freshness-duckdb   B2 freshness: an open connection that has answered q01 on version 0 of the
                     fresh stop_events copy (day 1); time the q01 that reads the latest version
                     (day 2 committed by the Spark step just before)

Usage: python3 -m transitometer.bench.axis_b_local freshness-duckdb [--prefix rt]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from typing import Any

from transitometer.axis_b import dialect
from transitometer.golden import suite
from transitometer.pipeline.layout import lakehouse_root

FRESHNESS_QUERY = "q01_on_time_by_mode_day"  # one row per (grp, service_date): shows new days


def freshness_sql(relation: str) -> str:
    """q01 with stop_events replaced by `relation` (the fresh copy, in each engine's terms)."""
    return re.sub(r"\bstop_events\b", relation, suite.query_sql(FRESHNESS_QUERY))


def freshness_duckdb(root: str, threads: int) -> dict[str, Any]:
    from transitometer.serve import lakehouse

    fresh = f"{root}_fresh/{dialect.TIME_TRAVEL_TABLE}"
    con = lakehouse.connect()
    con.execute(f"SET threads = {threads}")
    before = {r[1] for r in con.execute(freshness_sql(f"delta_scan('{fresh}', version => 0)"))
              .fetchall()}  # fmt: skip
    started = time.perf_counter()
    answer = con.execute(freshness_sql(f"delta_scan('{fresh}')")).fetch_arrow_table()
    visible_s = time.perf_counter() - started
    seen = sorted(set(answer.column("service_date").to_pylist()))
    return {
        "days_before": sorted(before),
        "days_after": seen,
        "visible_s": round(visible_s, 4),
        "ok": len(before) == 1 and len(seen) == 2,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=("freshness-duckdb",))
    parser.add_argument("--prefix", default="rt")
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--lakehouse", default=os.environ.get("LAKEHOUSE_DIR", "/data/lakehouse"))
    args = parser.parse_args(argv)
    root = f"{lakehouse_root(args.lakehouse, args.prefix)}/axis_b"
    result = freshness_duckdb(root, args.threads)
    print(json.dumps({"step": args.step, "result": result}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
