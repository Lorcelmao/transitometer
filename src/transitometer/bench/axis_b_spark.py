"""Axis B benchmark steps that need Spark and Delta (spark-submit in the tooling container).

  layout      per Axis B table: active files, data bytes (Delta detail), log bytes
  optimize    OPTIMIZE every Axis B table; files and bytes before and after
  vacuum      VACUUM RETAIN 0 HOURS; checks the folder then holds exactly the active files, the
              precondition of the zero-copy sub-arm (read_parquet over the folder)
  freshness   B1 freshness: a session that already answers q01 on day 1 of a fresh copy of
              stop_events; time the append commit of day 2, then the q01 that first sees it

Usage: spark-submit axis_b_spark.py layout|optimize|vacuum|freshness [--prefix rt]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from transitometer.axis_b import dialect
from transitometer.axis_b.delta_load import axis_b_root, build_session
from transitometer.bench.axis_b_local import freshness_sql

DAY = "service_date"


def _parquet_files(path: str) -> list[Path]:
    return [p for p in Path(path).rglob("*.parquet") if "_delta_log" not in p.parts]


def _log_bytes(path: str) -> int:
    return sum(p.stat().st_size for p in (Path(path) / "_delta_log").rglob("*") if p.is_file())


def detail(spark: SparkSession, path: str) -> dict[str, Any]:
    row = spark.sql(f"DESCRIBE DETAIL delta.`{path}`").first()
    return {
        "files": int(row["numFiles"]),
        "data_bytes": int(row["sizeInBytes"]),
        "log_bytes": _log_bytes(path),
        "files_in_folder": len(_parquet_files(path)),
    }


def layout(spark: SparkSession, root: str) -> dict[str, Any]:
    return {t: detail(spark, f"{root}/{t}") for t in dialect.tables()}


def optimize(spark: SparkSession, root: str) -> dict[str, Any]:
    tables = {}
    for table in dialect.tables():
        path = f"{root}/{table}"
        before = detail(spark, path)
        started = time.perf_counter()
        spark.sql(f"OPTIMIZE delta.`{path}`")
        seconds = round(time.perf_counter() - started, 2)
        tables[table] = {"before": before, "after": detail(spark, path), "optimize_s": seconds}
    return tables


def vacuum(spark: SparkSession, root: str) -> dict[str, Any]:
    spark.conf.set("spark.databricks.delta.retentionDurationCheck.enabled", "false")
    tables = {}
    for table in dialect.tables():
        path = f"{root}/{table}"
        spark.sql(f"VACUUM delta.`{path}` RETAIN 0 HOURS")
        after = detail(spark, path)
        after["zero_copy_valid"] = after["files"] == after["files_in_folder"]
        tables[table] = after
    return tables


def freshness(spark: SparkSession, root: str) -> dict[str, Any]:
    source = f"{root}/{dialect.TIME_TRAVEL_TABLE}"
    fresh = f"{root}_fresh/{dialect.TIME_TRAVEL_TABLE}"
    shutil.rmtree(fresh, ignore_errors=True)
    latest = spark.read.format("delta").load(source)
    days = sorted(r[0] for r in latest.select(DAY).distinct().collect())
    spark.read.format("delta").option("versionAsOf", 0).load(source).write.format("delta").save(
        fresh
    )
    spark.sql("DROP TABLE IF EXISTS fresh_stop_events")
    spark.sql(f"CREATE TABLE fresh_stop_events USING delta LOCATION '{fresh}'")
    query = freshness_sql("fresh_stop_events")
    before = {r[DAY] for r in spark.sql(query).collect()}  # the open session answers day 1
    started = time.perf_counter()
    latest.where(F.col(DAY) == days[1]).write.format("delta").mode("append").save(fresh)
    commit_s = time.perf_counter() - started
    started = time.perf_counter()
    answer = spark.sql(query).toArrow()
    visible_s = time.perf_counter() - started
    seen = sorted(set(answer.column(DAY).to_pylist()))
    return {
        "fresh_table": fresh,
        "days_before": sorted(before),
        "days_after": seen,
        "commit_s": round(commit_s, 4),
        "visible_s": round(visible_s, 4),
        "ok": sorted(before) == days[:1] and seen == days[:2],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=("layout", "optimize", "vacuum", "freshness"))
    parser.add_argument("--prefix", default="rt")
    parser.add_argument("--lakehouse", default=os.environ.get("LAKEHOUSE_DIR", "/data/lakehouse"))
    args = parser.parse_args(argv)
    root = axis_b_root(args.lakehouse, args.prefix)
    spark = build_session()
    spark.sparkContext.setLogLevel("WARN")
    steps = {"layout": layout, "optimize": optimize, "vacuum": vacuum, "freshness": freshness}
    result = steps[args.step](spark, root)
    print(json.dumps({"step": args.step, "root": root, "result": result}))
    spark.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
