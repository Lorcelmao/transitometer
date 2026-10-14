"""Axis B, B2: the suite in DuckDB over the Axis B Delta tables (`delta` extension).

Each table is a view over `delta_scan` of its latest version; q24/q25 read version 0 with
`delta_scan(path, version => 0)`.

Usage: python3 -m transitometer.axis_b.duckdb_arm [--prefix rt] [--threads 8]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import duckdb
import pyarrow as pa

from transitometer.axis_b import dialect
from transitometer.axis_b.runner import run_suite
from transitometer.pipeline.layout import lakehouse_root
from transitometer.serve import lakehouse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", default="rt")
    parser.add_argument("--threads", type=int, default=8, help="same core cap as Spark local[8]")
    parser.add_argument("--lakehouse", default=os.environ.get("LAKEHOUSE_DIR", "/data/lakehouse"))
    parser.add_argument("--exports", default=os.environ.get("EXPORTS_DIR", "/data/exports"))
    args = parser.parse_args(argv)
    root = f"{lakehouse_root(args.lakehouse, args.prefix)}/axis_b"
    con = lakehouse.connect()
    con.execute(f"SET threads = {args.threads}")
    for table in dialect.tables():
        con.execute(f"CREATE VIEW {table} AS SELECT * FROM delta_scan('{root}/{table}')")

    def execute(sql: str) -> pa.Table:
        return con.execute(sql).fetch_arrow_table()

    time_travel = f"delta_scan('{root}/{dialect.TIME_TRAVEL_TABLE}', version => 0)"
    record = run_suite("duckdb", execute, time_travel, Path(args.exports) / "axis-b" / "duckdb")
    record.update({"version": duckdb.__version__, "threads": args.threads, "tables": root})
    print(json.dumps(record))
    return 0


if __name__ == "__main__":
    sys.exit(main())
