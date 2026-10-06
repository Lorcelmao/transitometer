"""Axis A, Spark arm: W1 and W2 from the passage stream (Structured Streaming).

Reads `rt.passages` from the offsets recorded by the producer and writes:
  kpi.spark.w1   1-minute tumbling event-time windows of arrival delay per (route, stop)
  kpi.spark.w2   the BR2 headway of each passage (keyed state, transitometer.axis_a.headway_state)

Event time is the observed arrival; the watermark trails the largest event time seen by 120 s.
The end-of-stream marker advances the watermark past every real passage and is then discarded.
The parity run drains the topic with a processing-time trigger and stops each query once it has
read the recorded end offsets and run a batch without input under the final watermark. (Trigger
availableNow stops after the last batch with data, before that batch, so the last windows would
never close.) The benchmark (S10) uses the same job with `--trigger "10 seconds"`.

Usage: spark-submit axis_a_spark.py --record /data/exports/axis-a/produce-record.json [--fresh]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from collections.abc import Iterator
from datetime import datetime
from typing import Any

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.streaming import StreamingQuery
from pyspark.sql.streaming.state import GroupState, GroupStateTimeout
from pyspark.sql.types import (
    DoubleType,
    LongType,
    StringType,
    StructField,
    StructType,
)

from transitometer.axis_a import headway_state as hs

WATERMARK_S = 120
END_OFFSET_S = 86_400  # the producer's end marker: one day after the last passage
KEY = ("grp", "service_date", "route_id", "stop_id")
END = "__end__"
CHECKPOINTS = "/data/checkpoints/axis-a/spark"
PASSAGE = StructType(
    [
        StructField("grp", StringType()),
        StructField("service_date", StringType()),
        StructField("route_id", StringType()),
        StructField("stop_id", StringType()),
        StructField("service_hour", LongType()),
        StructField("trip_key", StringType()),
        StructField("trip_id", StringType()),
        StructField("unit", StringType()),
        StructField("source", StringType()),
        StructField("observed_arrival", LongType()),
        StructField("delay_s", LongType()),
        StructField("ref_headway_s", DoubleType()),
    ]
)
LONGS = ("service_hour", "observed_arrival", "headway_s")
W2_OUTPUT = StructType(
    [
        StructField(
            name,
            LongType()
            if name in LONGS
            else DoubleType()
            if name == "ref_headway_s"
            else StringType(),
        )
        for name in hs.OUTPUT_FIELDS
    ]
)
W2_STATE = StructType(
    [
        StructField("last", StringType()),
        StructField("buffer", StringType()),
        StructField("late", LongType()),
    ]
)


def passages(
    spark: SparkSession, bootstrap: str, topic: str, starting: dict[str, int], max_offsets: int
) -> DataFrame:
    """Parsed passages with an event-time watermark; the end marker only moves the watermark."""
    raw = (
        spark.readStream.format("kafka")
        .option("kafka.bootstrap.servers", bootstrap)
        .option("subscribe", topic)
        .option("startingOffsets", json.dumps({topic: starting}))
        .option("maxOffsetsPerTrigger", max_offsets)
        .option("failOnDataLoss", "true")
        .load()
    )
    parsed = raw.select(F.from_json(F.col("value").cast("string"), PASSAGE).alias("p")).select(
        "p.*"
    )
    watermarked = parsed.withColumn(
        "event_time", F.timestamp_seconds("observed_arrival")
    ).withWatermark("event_time", f"{WATERMARK_S} seconds")
    # No filter here: Catalyst pushes filters below EventTimeWatermark, which would remove the
    # end marker before the watermark sees it. Each workload discards the marker itself.
    return watermarked


def w1(df: DataFrame) -> DataFrame:
    windowed = (
        # Aggregate every row and count only delays: the end marker has none, and a filter on the
        # aggregate (delays > 0) cannot be pushed below the watermark.
        df.groupBy(*KEY, F.window("event_time", "1 minute")).agg(
            F.count("delay_s").alias("delays"),
            F.sum("delay_s").alias("delay_sum_s"),
            F.avg("delay_s").alias("mean_delay_s"),
            F.min("delay_s").alias("min_delay_s"),
            F.max("delay_s").alias("max_delay_s"),
            F.stddev_pop("delay_s").alias("stddev_delay_s"),
        )
    )
    return windowed.where(F.col("delays") > 0).select(
        *KEY,
        F.unix_timestamp(F.col("window.start")).alias("window_start"),
        "delays",
        "delay_sum_s",
        "mean_delay_s",
        "min_delay_s",
        "max_delay_s",
        "stddev_delay_s",
    )


def _records(frame: Any) -> list[dict[str, Any]]:
    """Passage fields as plain Python values (NaN and NA become None).

    The event_time column stays in the input because it carries the watermark; the state keeps
    only the passage fields.
    """
    frame = frame[PASSAGE.fieldNames()]
    clean = frame.astype(object).where(frame.notna(), None)
    return [
        {k: (v.item() if hasattr(v, "item") else v) for k, v in r.items()}
        for r in clean.to_dict("records")
    ]


def headways(key: tuple[Any, ...], frames: Iterator[Any], state: GroupState) -> Iterator[Any]:
    import pandas as pd

    if key[0] == END:  # the end marker only moves the watermark
        yield pd.DataFrame([], columns=list(hs.OUTPUT_FIELDS))
        return
    st = hs.HeadwayState()
    if state.exists:
        last, buffer, late = state.get
        st = hs.HeadwayState(json.loads(last) if last else None, json.loads(buffer), int(late))
    if not state.hasTimedOut:
        for frame in frames:
            hs.add(st, _records(frame))
    rows = hs.release(st, state.getCurrentWatermarkMs() / 1000)
    state.update((json.dumps(st.last) if st.last else None, json.dumps(st.buffer), st.late))
    earliest = hs.earliest(st)
    if earliest is not None:
        state.setTimeoutTimestamp((earliest + 1) * 1000)  # fires once the watermark passes it
    yield pd.DataFrame(rows, columns=list(hs.OUTPUT_FIELDS))


def w2(df: DataFrame) -> DataFrame:
    return (
        df.select(*PASSAGE.fieldNames(), "event_time")
        .groupBy(*KEY)
        .applyInPandasWithState(
            headways, W2_OUTPUT, W2_STATE, "append", GroupStateTimeout.EventTimeTimeout
        )
    )


def to_kafka(df: DataFrame, bootstrap: str, topic: str, name: str, trigger: str) -> StreamingQuery:
    out = df.select(
        F.concat_ws("|", *KEY).alias("key"), F.to_json(F.struct(*df.columns)).alias("value")
    )
    writer = (
        out.writeStream.format("kafka")
        .option("kafka.bootstrap.servers", bootstrap)
        .option("topic", topic)
        .option("checkpointLocation", f"{CHECKPOINTS}/{name}")
        .outputMode("append")
        .queryName(name)
    )
    return writer.trigger(processingTime=trigger).start()


def recreate_topics(bootstrap: str, topics: list[str], partitions: int = 6) -> None:
    from transitometer.axis_a.produce import recreate

    for topic in topics:
        recreate(bootstrap, topic, partitions)


def _progress(p: Any) -> dict[str, Any]:
    """A progress report as a dict (Spark 4 returns objects; their .json is the raw JSON)."""
    return json.loads(p.json) if hasattr(p, "json") else dict(p)


def summary(query: StreamingQuery) -> dict[str, Any]:
    progress = [_progress(p) for p in query.recentProgress if p]
    end = progress[-1]["sources"][0]["endOffset"] if progress else None
    return {
        "batches": len(progress),
        "input_rows": sum(p["numInputRows"] for p in progress),
        "dropped_by_watermark": sum(
            op.get("numRowsDroppedByWatermark", 0)
            for p in progress
            for op in p.get("stateOperators", [])
        ),
        "end_offsets": json.loads(end) if isinstance(end, str) else end,
    }


def drained(query: StreamingQuery, topic: str, expected: dict[str, int], final_wm_ms: int) -> bool:
    """The topic is read to the recorded end and a batch without input has run with the final
    watermark (the end marker's), so every window and timer has fired."""
    if not query.lastProgress:
        return False
    progress = _progress(query.lastProgress)
    end = progress["sources"][0]["endOffset"]
    end = json.loads(end) if isinstance(end, str) else end
    read = {str(k): v for k, v in (end or {}).get(topic, {}).items()}
    mark = progress.get("eventTime", {}).get("watermark")
    if mark is None or read != expected or progress["numInputRows"] != 0:
        return False
    when = datetime.fromisoformat(mark.replace("Z", "+00:00"))
    return when.timestamp() * 1000 >= final_wm_ms


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", required=True, help="producer record (offsets)")
    parser.add_argument("--bootstrap", default="kafka:9092")
    parser.add_argument("--trigger", default="1 second", help="processing-time trigger interval")
    parser.add_argument("--max-offsets", type=int, default=100_000, help="per trigger")
    parser.add_argument("--fresh", action="store_true", help="new output topics and checkpoints")
    args = parser.parse_args(argv)
    with open(args.record, encoding="utf-8") as handle:
        record = json.load(handle)
    topic = record["topic"]
    starting = {p: b["start"] for p, b in record["partitions"].items()}
    expected = {p: b["end"] for p, b in record["partitions"].items()}
    # The end marker sits one day after the last passage; the watermark trails it by 120 s.
    final_wm_ms = (record["last_arrival"] + END_OFFSET_S - WATERMARK_S) * 1000
    outputs = {"w1": "kpi.spark.w1", "w2": "kpi.spark.w2"}
    if args.fresh:
        shutil.rmtree(CHECKPOINTS, ignore_errors=True)
        recreate_topics(args.bootstrap, list(outputs.values()))

    spark = (
        SparkSession.builder.appName("axis-a-spark")
        .config("spark.sql.shuffle.partitions", "8")
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")
    started = time.perf_counter()
    source = passages(spark, args.bootstrap, topic, starting, args.max_offsets)
    queries = {
        "w1": to_kafka(w1(source), args.bootstrap, outputs["w1"], "w1", args.trigger),
        "w2": to_kafka(w2(source), args.bootstrap, outputs["w2"], "w2", args.trigger),
    }
    finished: dict[str, float] = {}
    while len(finished) < len(queries):
        for name, query in queries.items():
            if name in finished:
                continue
            if not query.isActive:
                raise RuntimeError(f"query {name} stopped early: {query.exception()}")
            if drained(query, topic, expected, final_wm_ms):
                finished[name] = round(time.perf_counter() - started, 1)
                print(f"progress {name} drained after {finished[name]}s", flush=True)
                query.stop()
        time.sleep(1)
    result = {
        "engine": f"Spark {spark.version}",
        "topic": topic,
        "trigger": args.trigger,
        "max_offsets_per_trigger": args.max_offsets,
        "watermark": f"{WATERMARK_S} seconds",
        "parallelism": 8,
        "drained_s": finished,
        **{name: {**summary(q), "read_to_recorded_end": True} for name, q in queries.items()},
    }
    print(json.dumps(result))
    spark.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
