"""Export lakehouse Delta tables as single Parquet files for the golden comparison.

Runs in the Spark tooling container (DuckDB + Delta extension); the exports folder is the host
data root's exports/, where golden/compare.py reads them next to the golden tables.

Usage: python3 -m transitometer.pipeline.export --layer silver --tables stop_events [--prefix rt]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from transitometer.pipeline.layout import lakehouse_root
from transitometer.serve import lakehouse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", default="rt")
    parser.add_argument("--layer", choices=["silver", "gold"], required=True)
    parser.add_argument("--tables", nargs="+", required=True)
    parser.add_argument("--lakehouse", default=os.environ.get("LAKEHOUSE_DIR", "/data/lakehouse"))
    parser.add_argument("--exports", default=os.environ.get("EXPORTS_DIR", "/data/exports"))
    args = parser.parse_args(argv)
    source = f"{lakehouse_root(args.lakehouse, args.prefix)}/{args.layer}"
    target = Path(args.exports) / args.prefix / args.layer
    target.mkdir(parents=True, exist_ok=True)
    con = lakehouse.connect()
    rows = {}
    for table in args.tables:
        out = target / f"{table}.parquet"
        con.execute(
            f"COPY (SELECT * FROM delta_scan('{source}/{table}')) TO '{out}' "
            "(FORMAT parquet, COMPRESSION zstd)"
        )
        rows[table] = con.execute(f"SELECT count(*) FROM '{out}'").fetchone()[0]  # type: ignore[index]
        print(f"progress export {table}: {rows[table]:,} rows", file=sys.stderr, flush=True)
    print(json.dumps({"layer": args.layer, "prefix": args.prefix, "exported": rows}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
