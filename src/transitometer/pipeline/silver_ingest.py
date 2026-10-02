"""Silver ingest: replayed Kafka feeds -> decoded Delta tables, with dedup, dead-letter and counts.

One availableNow Structured Streaming pass per feed: it reads everything in the topic, commits
the offsets to its checkpoint and stops, so a re-run with the same checkpoint appends nothing.

  <lakehouse>/silver/trip_update_rows/<feed>   one row per stop-time update (archive-shaped)
  <lakehouse>/silver/vehicle_positions         one row per vehicle entity
  <lakehouse>/silver/feed_snapshots            one row per snapshot marker
  <lakehouse>/silver/dead_letter               messages that failed decoding or required fields
  <lakehouse>/meta/ingest_log                  one row per feed per run (conservation counts)

Column names and meanings follow the archive (replay/encode.py), so Silver can be compared with
the archive and the golden reference column for column. Tables are partitioned by `feed_date`
(UTC day of the feed timestamp); service days are assigned by the stop-event step.

Duplicates are exact re-deliveries (same key, snapshot and payload bytes); they are dropped
within a watermark on feed time that is longer than any injected lateness.

Usage: python3 -m transitometer.pipeline.silver_ingest --prefix rt [--feeds ...] [--lakehouse ...]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from pyspark.sql import Column, DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.protobuf.functions import from_protobuf
from pyspark.sql.streaming import StreamingQuery

from transitometer.pipeline.layout import lakehouse_root
from transitometer.replay import encode
from transitometer.replay.archive import FEEDS, Feed
from transitometer.replay.run import data_topic, marker_topic

DESCRIPTOR = os.environ.get("GTFS_RT_DESCRIPTOR", "/opt/transitometer/gtfs-realtime.desc")
PROGRESS_EVERY_S = 30
WATERMARK = "10 minutes"  # longer than the largest injected lateness (120 s)
PROTOBUF_OPTIONS = {"mode": "PERMISSIVE", "enums.as.ints": "true"}
MARKER_SCHEMA = (
    "feed string, source_file string, feed_timestamp long, fetch_timestamp_us long, "
    "entities long, rows long"
)


def header(name: str) -> Column:
    """Value of one Kafka header as a string (NULL when absent or empty)."""
    matches = F.filter(F.col("headers"), lambda h: h["key"] == F.lit(name))
    value = F.element_at(matches, 1)["value"].cast("string")
    return F.when(value != "", value)


def _fields(prefix: str, mapping: Mapping[str, str]) -> list[Column]:
    """Archive columns from one protobuf message: {archive column: proto field} -> selects."""
    return [F.col(f"{prefix}.{field}").alias(column) for column, field in mapping.items()]


def trip_update_columns() -> list[Column]:
    """Entity-level trip-update columns, in archive order (stop columns come after explode)."""
    tu = "e.trip_update"
    return [
        F.col("e.id").alias("entity_id"),
        F.col("e.is_deleted").alias("is_deleted"),
        *_fields(f"{tu}.trip", encode._TU_TRIP_FIELDS),
        *_fields(f"{tu}.trip.modified_trip", encode._TU_MODIFIED_TRIP),
        *_fields(f"{tu}.vehicle", encode._TU_VEHICLE_FIELDS),
        *_fields(tu, encode._TU_TOP_FIELDS),
        *_fields(f"{tu}.trip_properties", encode._TU_TRIP_PROPERTIES),
    ]


def stop_columns() -> list[Column]:
    """Stop-time-update columns from the exploded `stu` struct, in archive order."""
    events = [_fields(f"stu.{event}", mapping) for event, mapping in encode._STU_EVENTS.items()]
    return [
        *_fields("stu", encode._STU_FIELDS),
        *[column for event in events for column in event],
        *_fields("stu.stop_time_properties", encode._STU_PROPERTIES),
    ]


def vehicle_columns() -> list[Column]:
    vp = "e.vehicle"
    return [
        F.col("e.id").alias("entity_id"),
        F.col("e.is_deleted").alias("is_deleted"),
        *_fields(f"{vp}.trip", encode._TRIP_FIELDS),
        *_fields(f"{vp}.vehicle", encode._VEHICLE_FIELDS),
        *_fields(f"{vp}.position", encode._POSITION_FIELDS),
        *[F.col(f"{vp}.{field}").alias(field) for field in encode._TOP_FIELDS],
    ]


def build_session() -> SparkSession:
    return (
        SparkSession.builder.appName("transitometer-silver-ingest")
        .master(os.environ.get("SPARK_MASTER", "local[8]"))
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config(
            "spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog"
        )
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.streaming.numRecentProgressUpdates", "100000")  # for the counts
        # Storage budget: keep 2 state versions (no rollback is ever needed), zstd for Parquet.
        .config("spark.sql.streaming.minBatchesToRetain", "2")
        # Consolidate the dedup state every 2 batches so superseded delta files are cleaned up
        # (the default of 10 kept every key of a whole replay: 6 GB of checkpoints). Stays
        # compatible with existing checkpoints, unlike switching the state store provider.
        .config("spark.sql.streaming.stateStore.minDeltasForSnapshot", "2")
        .config("spark.sql.parquet.compression.codec", "zstd")
        .getOrCreate()
    )


def kafka_source(spark: SparkSession, bootstrap: str, topic: str) -> DataFrame:
    return (
        spark.readStream.format("kafka")
        .option("kafka.bootstrap.servers", bootstrap)
        .option("subscribe", topic)
        .option("startingOffsets", "earliest")
        .option("includeHeaders", "true")
        .option("maxOffsetsPerTrigger", 2_000_000)  # bounded batches keep memory flat
        .load()
    )


def decoded(source: DataFrame) -> DataFrame:
    """Kafka rows -> snapshot columns + decoded entity `e` + the reason it is invalid (or NULL)."""
    frame = source.select(
        from_protobuf(
            F.col("value"), "transit_realtime.FeedEntity", DESCRIPTOR, PROTOBUF_OPTIONS
        ).alias("e"),
        F.col("key").cast("string").alias("message_key"),
        F.sha2(F.col("value"), 256).alias("payload_sha256"),
        F.col("value").alias("payload"),
        F.col("topic").alias("kafka_topic"),
        F.col("partition").alias("kafka_partition"),
        F.col("offset").alias("kafka_offset"),
        header("feed").alias("feed"),
        header("feed_timestamp").cast("long").alias("feed_timestamp"),
        header("fetch_timestamp_us").cast("long").alias("fetch_timestamp_us"),
        header("source_file").alias("source_file"),
    )
    reason = (
        F.when(F.col("e").isNull(), "undecodable payload")
        .when(F.col("e.id").isNull(), "missing entity id")
        .when(F.col("feed_timestamp").isNull(), "missing feed_timestamp header")
        .when(F.col("source_file").isNull(), "missing source_file header")
    )
    return frame.withColumn("invalid_reason", reason)


def valid_rows(frame: DataFrame, kind: str) -> DataFrame:
    """Deduplicated, archive-shaped rows of the valid messages."""
    deduped = (
        frame.where(F.col("invalid_reason").isNull())
        .withColumn("feed_time", F.timestamp_seconds("feed_timestamp"))
        .withWatermark("feed_time", WATERMARK)
        .dropDuplicatesWithinWatermark(["message_key", "source_file", "payload_sha256"])
    )
    snapshot = [
        "feed",
        "source_file",
        "feed_timestamp",
        "fetch_timestamp_us",
        F.to_date("feed_time").alias("feed_date"),
    ]
    lineage = ["kafka_partition", "kafka_offset"]
    if kind == "vehicle_positions":
        return deduped.select(*snapshot, *vehicle_columns(), *lineage)
    exploded = deduped.select(
        *snapshot,
        *trip_update_columns(),
        F.explode_outer("e.trip_update.stop_time_update").alias("stu"),
        *lineage,
    )
    return exploded.select(
        *snapshot[:4], "feed_date", *encode.ENTITY_COLUMNS, *stop_columns(), *lineage
    )


def dead_letters(frame: DataFrame) -> DataFrame:
    return frame.where(F.col("invalid_reason").isNotNull()).select(
        "kafka_topic",
        "kafka_partition",
        "kafka_offset",
        "message_key",
        "feed",
        "source_file",
        "feed_timestamp",
        "invalid_reason",
        "payload",
        F.current_date().alias("ingest_date"),
    )


def markers(source: DataFrame) -> DataFrame:
    parsed = source.select(F.from_json(F.col("value").cast("string"), MARKER_SCHEMA).alias("m"))
    return (
        parsed.select("m.*")
        .withColumn("feed_time", F.timestamp_seconds("feed_timestamp"))
        .withWatermark("feed_time", WATERMARK)
        .dropDuplicatesWithinWatermark(["feed", "source_file"])
        .withColumn("feed_date", F.to_date("feed_time"))
        .drop("feed_time")
    )


def write(frame: DataFrame, path: str, checkpoint: str, partition: str) -> StreamingQuery:
    return (
        frame.writeStream.format("delta")
        .option("checkpointLocation", checkpoint)
        .partitionBy(partition)
        .outputMode("append")
        .trigger(availableNow=True)
        .start(path)
    )


def _counts(query: StreamingQuery) -> dict[str, int]:
    """Rows read and rows dropped by state operators, summed over every micro-batch.

    The Delta streaming sink does not report rows written, so outputs are tallied from the
    tables themselves (see _tally).
    """
    progress = query.recentProgress
    return {
        "input": sum(p["numInputRows"] for p in progress),
        "late_dropped": sum(
            s.get("numRowsDroppedByWatermark", 0) for p in progress for s in p["stateOperators"]
        ),
        "duplicates_dropped": sum(
            s.get("customMetrics", {}).get("numDroppedDuplicateRows", 0)
            for p in progress
            for s in p["stateOperators"]
        ),
    }


def _await(name: str, main: StreamingQuery, queries: tuple[StreamingQuery, ...]) -> None:
    """Wait for every query, printing the main one's progress every PROGRESS_EVERY_S."""
    started = time.monotonic()
    while main.isActive:
        main.awaitTermination(PROGRESS_EVERY_S)
        read = sum(p["numInputRows"] for p in main.recentProgress)
        elapsed = time.monotonic() - started
        print(
            f"progress silver {name}: {read:,} messages read, {read / elapsed:,.0f}/s",
            file=sys.stderr,
            flush=True,
        )
    for query in queries:
        query.awaitTermination()  # also re-raises a query's failure


def _tally(spark: SparkSession, path: str, where: Column | None = None) -> dict[str, int]:
    """Rows and distinct Kafka messages (partition, offset) currently in one Delta table."""
    if not os.path.exists(f"{path}/_delta_log"):
        return {"rows": 0, "messages": 0}
    table = spark.read.format("delta").load(path)
    if where is not None:
        table = table.where(where)
    row = table.agg(
        F.count(F.lit(1)).alias("rows"),
        F.count_distinct("kafka_partition", "kafka_offset").alias("messages"),
    ).first()
    return {"rows": int(row["rows"]), "messages": int(row["messages"])}


def _snapshot_count(spark: SparkSession, path: str, feed: str) -> int:
    if not os.path.exists(f"{path}/_delta_log"):
        return 0
    count: int = spark.read.format("delta").load(path).where(F.col("feed") == feed).count()
    return count


def ingest_feed(
    spark: SparkSession,
    feed: Feed,
    prefix: str,
    bootstrap: str,
    lakehouse: str,
    checkpoints: str,
) -> dict[str, Any]:
    kind, name = feed.name.split(".", 1)[0], feed.name
    frame = decoded(kafka_source(spark, bootstrap, data_topic(prefix, feed)))
    table = (
        f"{lakehouse}/silver/vehicle_positions"
        if kind == "vehicle_positions"
        else f"{lakehouse}/silver/trip_update_rows/{name.split('.', 1)[1]}"
    )
    dead_path, snaps_path = f"{lakehouse}/silver/dead_letter", f"{lakehouse}/silver/feed_snapshots"
    topic_filter = F.col("kafka_topic") == data_topic(prefix, feed)
    before = (
        _tally(spark, table),
        _tally(spark, dead_path, topic_filter),
        _snapshot_count(spark, snaps_path, name),
    )
    rows = write(valid_rows(frame, kind), table, f"{checkpoints}/{name}/rows", "feed_date")
    dead = write(
        dead_letters(frame),
        dead_path,
        f"{checkpoints}/{name}/dead_letter",
        "ingest_date",
    )
    snaps = write(
        markers(kafka_source(spark, bootstrap, marker_topic(prefix, feed))),
        snaps_path,
        f"{checkpoints}/{name}/snapshots",
        "feed_date",
    )
    _await(name, rows, (rows, dead, snaps))
    valid, snapshot = _counts(rows), _counts(snaps)
    after = (
        _tally(spark, table),
        _tally(spark, dead_path, topic_filter),
        _snapshot_count(spark, snaps_path, name),
    )
    kept = after[0]["messages"] - before[0]["messages"]
    dead_lettered = after[1]["messages"] - before[1]["messages"]
    # Conservation over Kafka messages: every message read is kept (one message may explode
    # into many stop rows), dropped as a duplicate, dropped as late, or dead-lettered.
    accounted = kept + valid["duplicates_dropped"] + valid["late_dropped"] + dead_lettered
    return {
        "feed": name,
        "prefix": prefix,
        "messages_in": valid["input"],
        "messages_kept": kept,
        "duplicates_dropped": valid["duplicates_dropped"],
        "late_dropped": valid["late_dropped"],
        "dead_lettered": dead_lettered,
        "balanced": accounted == valid["input"],
        "rows_out": after[0]["rows"] - before[0]["rows"],
        "rows_total": after[0]["rows"],
        "snapshots_in": snapshot["input"],
        "snapshots_out": after[2] - before[2],
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def log_run(spark: SparkSession, lakehouse: str, entries: list[dict[str, Any]]) -> None:
    log = spark.createDataFrame(entries).write.format("delta").mode("append")
    log.option("mergeSchema", "true").save(  # the log gains columns as the job evolves
        f"{lakehouse}/meta/ingest_log"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", default="rt")
    parser.add_argument("--feeds", nargs="*", default=[f.name for f in FEEDS])
    parser.add_argument("--lakehouse", default=os.environ.get("LAKEHOUSE_DIR", "/data/lakehouse"))
    parser.add_argument(
        "--checkpoints", default=os.environ.get("CHECKPOINT_DIR", "/data/checkpoints")
    )
    parser.add_argument("--bootstrap", default=os.environ.get("KAFKA_BOOTSTRAP", "kafka:9092"))
    args = parser.parse_args(argv)
    lakehouse = lakehouse_root(args.lakehouse, args.prefix)
    checkpoints = lakehouse_root(args.checkpoints, args.prefix) + "/silver_ingest"
    spark = build_session()
    spark.sparkContext.setLogLevel("WARN")
    entries = []
    for feed in (f for f in FEEDS if f.name in args.feeds):
        print(f"progress silver {feed.name}: started", file=sys.stderr, flush=True)
        entries.append(
            ingest_feed(spark, feed, args.prefix, args.bootstrap, lakehouse, checkpoints)
        )
        print(f"progress silver {feed.name}: {entries[-1]}", file=sys.stderr, flush=True)
    log_run(spark, lakehouse, entries)
    spark.stop()
    print(json.dumps({"feeds": entries}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
