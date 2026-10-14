"""Axis B dataset: the suite's tables copied into lakehouse/axis_b, one service day per commit.

The kept lakehouse writes each table in one overwrite, so its Delta versions do not line up with
service days. Here every table with a `service_date` is committed one service day at a time,
oldest first, so version 0 holds exactly the first service day: the Delta version read that the
time-travel queries (q24, q25) stand for. Tables without a service date take one commit. Any
earlier copy is removed first, so versions always start at 0.

The copy is a benchmark-only derivative. It is written only under lakehouse/axis_b, reads each
validated Silver/Gold table at a pinned Delta version, records that source path and version in
every commit's `userMetadata` and in the run report, and checks that no source table gained a
version while it ran. Nothing outside axis_b is written.

Usage: spark-submit delta_load.py [--prefix rt]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from transitometer.axis_b import dialect
from transitometer.pipeline.layout import lakehouse_root

SILVER_TABLES = {"stop_events"}  # every other table the suite reads is Gold
DAY = "service_date"


def build_session() -> SparkSession:
    return (
        SparkSession.builder.appName("transitometer-axis-b-load")
        .master(os.environ.get("SPARK_MASTER", "local[8]"))
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config(
            "spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog"
        )
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.parquet.compression.codec", "zstd")
        .getOrCreate()
    )


def axis_b_root(lakehouse: str, prefix: str) -> str:
    return f"{lakehouse_root(lakehouse, prefix)}/axis_b"


def latest_version(spark: SparkSession, path: str) -> int:
    version: int = spark.sql(f"DESCRIBE HISTORY delta.`{path}` LIMIT 1").first()["version"]
    return version


def copy_table(spark: SparkSession, source: str, target: str) -> dict[str, object]:
    """Copy one table; per-day commits when it has a service date. Returns its check record.

    The source is read at a pinned Delta version and never written; every commit of the copy
    carries that provenance in its Delta `userMetadata`, and the source version is checked
    unchanged afterwards.
    """
    shutil.rmtree(target, ignore_errors=True)
    source_version = latest_version(spark, source)
    frame = spark.read.format("delta").option("versionAsOf", source_version).load(source)
    rows = frame.count()
    provenance = {"source": source, "source_version": source_version}
    started = time.perf_counter()
    if DAY not in frame.columns:
        frame.write.format("delta").option("userMetadata", json.dumps(provenance)).save(target)
        days: list[str] = []
    else:
        days = sorted(r[0] for r in frame.select(DAY).distinct().collect())
        for version, day in enumerate(days):
            mode = "overwrite" if version == 0 else "append"
            metadata = json.dumps({**provenance, DAY: day})
            (
                frame.where(F.col(DAY) == day)
                .write.format("delta")
                .mode(mode)
                .option("userMetadata", metadata)
                .save(target)
            )
    seconds = round(time.perf_counter() - started, 1)
    copied = spark.read.format("delta").load(target)
    history = spark.sql(f"DESCRIBE HISTORY delta.`{target}`").collect()
    versions = len(history)
    record: dict[str, object] = {
        **provenance,
        "rows": rows,
        "copied_rows": copied.count(),
        "service_days": days,
        "versions": versions,
        "write_s": seconds,
    }
    source_unchanged = latest_version(spark, source) == source_version
    record["source_unchanged"] = source_unchanged
    checks = [
        record["copied_rows"] == rows,
        versions == max(len(days), 1),
        source_unchanged,
        all(json.loads(h["userMetadata"])["source"] == source for h in history),
    ]
    if days:
        first = spark.read.format("delta").option("versionAsOf", 0).load(target)
        first_days = [r[0] for r in first.select(DAY).distinct().collect()]
        first_rows = first.count()
        record["version_0_days"] = first_days
        record["version_0_rows"] = first_rows
        checks += [
            first_days == days[:1],
            first_rows == frame.where(F.col(DAY) == days[0]).count(),
        ]
    record["ok"] = all(checks)
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", default="rt")
    parser.add_argument("--lakehouse", default=os.environ.get("LAKEHOUSE_DIR", "/data/lakehouse"))
    args = parser.parse_args(argv)
    root = lakehouse_root(args.lakehouse, args.prefix)
    target_root = axis_b_root(args.lakehouse, args.prefix)
    spark = build_session()
    spark.sparkContext.setLogLevel("WARN")
    tables = {}
    for table in dialect.tables():
        layer = "silver" if table in SILVER_TABLES else "gold"
        print(f"progress axis-b load {table}", file=sys.stderr, flush=True)
        tables[table] = copy_table(spark, f"{root}/{layer}/{table}", f"{target_root}/{table}")
        tables[table]["layer"] = layer
    ok = all(t["ok"] for t in tables.values())
    print(json.dumps({"prefix": args.prefix, "target": target_root, "tables": tables, "ok": ok}))
    spark.stop()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
