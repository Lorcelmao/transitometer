"""Measure Spark full-scan time of one Parquet file (storage calibration, IMPLEMENTATION_PLAN §4.3).

Comparing the read-only Windows mount with a copy on a Docker volume decides whether scale runs
must be staged inside Docker. Prints one JSON line: {"seconds": ..., "rows": ...}.
"""

from __future__ import annotations

import json
import os
import sys
import time

from pyspark.sql import SparkSession
from pyspark.sql import functions as F


def main(argv: list[str] | None = None) -> int:
    path = (argv or sys.argv[1:])[0]
    spark = (
        SparkSession.builder.appName("transitometer-read-probe")
        .master(os.environ.get("SPARK_MASTER", "local[8]"))
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")
    started = time.perf_counter()
    # Aggregate several wide columns so every data page is actually read and decoded.
    row = (
        spark.read.parquet(path)
        .agg(
            F.count(F.lit(1)).alias("rows"),
            F.countDistinct("trip_id").alias("trips"),
            F.max("arrival_time").alias("max_arrival"),
            F.sum(F.length("stop_id")).alias("stop_chars"),
        )
        .collect()[0]
    )
    seconds = time.perf_counter() - started
    spark.stop()
    print(json.dumps({"seconds": round(seconds, 2), "rows": row["rows"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
