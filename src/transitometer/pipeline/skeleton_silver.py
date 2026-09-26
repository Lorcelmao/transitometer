"""Walking-skeleton Spark job: Kafka protobuf vehicle positions -> Silver Delta table.

Runs as a Structured Streaming query with trigger(availableNow): it processes everything in
the topic, commits offsets to the checkpoint, and stops. Re-running with the same checkpoint
must append nothing (exactly-once Delta sink). Prints one JSON summary line.

Usage: spark-submit skeleton_silver.py --topic <t> --table <delta path> --checkpoint <dir>
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.protobuf.functions import from_protobuf

DESCRIPTOR = os.environ.get("GTFS_RT_DESCRIPTOR", "/opt/transitometer/gtfs-realtime.desc")


def header(name: str) -> F.Column:
    """Value of one Kafka header as a string."""
    matches = F.filter(F.col("headers"), lambda h: h["key"] == F.lit(name))
    return F.element_at(matches, 1)["value"].cast("string")


def build_session() -> SparkSession:
    return (
        SparkSession.builder.appName("transitometer-skeleton-silver")
        .master(os.environ.get("SPARK_MASTER", "local[8]"))
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config(
            "spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog"
        )
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate()
    )


def run(args: argparse.Namespace) -> dict[str, int]:
    spark = build_session()
    spark.sparkContext.setLogLevel("WARN")
    before = _count(spark, args.table)

    source = (
        spark.readStream.format("kafka")
        .option("kafka.bootstrap.servers", args.bootstrap)
        .option("subscribe", args.topic)
        .option("startingOffsets", "earliest")
        .option("includeHeaders", "true")
        .load()
    )
    entity = from_protobuf(F.col("value"), "transit_realtime.FeedEntity", descFilePath=DESCRIPTOR)
    silver = source.select(
        entity.alias("e"),
        F.col("partition").alias("kafka_partition"),
        F.col("offset").alias("kafka_offset"),
        F.col("timestamp").alias("kafka_append_ts"),
        header("feed").alias("feed"),
        header("feed_timestamp").cast("long").alias("feed_timestamp"),
        header("source_file").alias("source_file"),
    ).select(
        "feed",
        "feed_timestamp",
        "source_file",
        F.col("e.id").alias("entity_id"),
        F.col("e.is_deleted").alias("is_deleted"),
        F.col("e.vehicle.trip.trip_id").alias("trip_id"),
        F.col("e.vehicle.trip.route_id").alias("route_id"),
        F.col("e.vehicle.trip.direction_id").alias("direction_id"),
        F.col("e.vehicle.trip.start_date").alias("start_date"),
        F.col("e.vehicle.vehicle.id").alias("vehicle_id"),
        F.col("e.vehicle.position.latitude").alias("latitude"),
        F.col("e.vehicle.position.longitude").alias("longitude"),
        F.col("e.vehicle.position.bearing").alias("bearing"),
        F.col("e.vehicle.stop_id").alias("stop_id"),
        F.col("e.vehicle.current_status").alias("current_status"),
        F.col("e.vehicle.timestamp").cast("long").alias("vehicle_timestamp"),
        "kafka_partition",
        "kafka_offset",
        "kafka_append_ts",
    )
    query = (
        silver.writeStream.format("delta")
        .option("checkpointLocation", args.checkpoint)
        .outputMode("append")
        .trigger(availableNow=True)
        .start(args.table)
    )
    query.awaitTermination()
    after = _count(spark, args.table)
    spark.stop()
    return {"rows_before": before, "rows_after": after, "rows_appended": after - before}


def _count(spark: SparkSession, table: str) -> int:
    if not os.path.exists(os.path.join(table, "_delta_log")):
        return 0
    count: int = spark.read.format("delta").load(table).count()
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--table", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--bootstrap", default=os.environ.get("KAFKA_BOOTSTRAP", "kafka:9092"))
    print(json.dumps(run(parser.parse_args(argv))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
