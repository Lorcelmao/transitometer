"""Axis B, B1: the suite in Spark SQL over the Axis B Delta tables.

Each table is registered in the session catalog as an external Delta table at its path, so the
queries use plain table names and q24/q25 can read `stop_events VERSION AS OF 0`.

Usage: spark-submit spark_arm.py [--prefix rt] [--passes 1] [--answers spark]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pyarrow as pa
import pyspark

from transitometer.axis_b import dialect
from transitometer.axis_b.delta_load import axis_b_root, build_session
from transitometer.axis_b.runner import run_suite


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", default="rt")
    parser.add_argument("--lakehouse", default=os.environ.get("LAKEHOUSE_DIR", "/data/lakehouse"))
    parser.add_argument("--exports", default=os.environ.get("EXPORTS_DIR", "/data/exports"))
    parser.add_argument("--passes", type=int, default=1, help="1 cold pass, then warm passes")
    parser.add_argument("--answers", default="spark", help="folder under exports/axis-b")
    args = parser.parse_args(argv)
    root = axis_b_root(args.lakehouse, args.prefix)
    spark = build_session()
    spark.sparkContext.setLogLevel("WARN")
    for table in dialect.tables():
        spark.sql(f"DROP TABLE IF EXISTS {table}")
        spark.sql(f"CREATE TABLE {table} USING delta LOCATION '{root}/{table}'")

    def execute(sql: str) -> pa.Table:
        return spark.sql(sql).toArrow()

    record = run_suite(
        "spark",
        execute,
        f"{dialect.TIME_TRAVEL_TABLE} VERSION AS OF 0",
        Path(args.exports) / "axis-b" / args.answers,
        args.passes,
    )
    record.update(
        {
            "version": pyspark.__version__,
            "master": spark.sparkContext.master,
            "cores": spark.sparkContext.defaultParallelism,
            "tables": root,
        }
    )
    print(json.dumps(record))
    spark.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
