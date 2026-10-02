"""Gold BR7 feed health: per feed and day, quality metrics checked against fixed thresholds.

Definitions follow golden/sql/12_feed_quality.sql (see its header for the rationale of every
metric), implemented here with the Spark DataFrame API, independently of that SQL. Lower is
better for every metric. Each feed gets every applicable check on every service day; a check
without data fails (value NULL). The score is the share of checks passed, 0-100.

Snapshot and fix metrics use the local calendar day of the snapshot; trip and event metrics use
the service day.
"""

from __future__ import annotations

from pyspark.sql import Column, DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from transitometer.pipeline.gold_delivery import METRES_PER_DEGREE
from transitometer.pipeline.service_days import TIMEZONE

THRESHOLDS = {
    "max_gap_s": 120.0,
    "missed_poll_share": 0.01,
    "header_lag_p99_s": 60.0,
    "unknown_stop_share": 0.01,
    "unknown_trip_share": 0.05,
    "stuck_share": 0.02,
    "not_run_share": 0.02,
    "ambiguous_share": 0.02,
    "fix_age_p99_s": 60.0,
    "stale_fix_share": 0.01,
    "jump_share": 0.001,
    "out_of_bbox_share": 0.001,
}
SNAPSHOT_METRICS = ("max_gap_s", "missed_poll_share", "header_lag_p99_s")
TRIP_UPDATE_METRICS = (
    "unknown_stop_share",
    "unknown_trip_share",
    "stuck_share",
    "not_run_share",
    "ambiguous_share",
)
POSITION_METRICS = ("fix_age_p99_s", "stale_fix_share", "jump_share", "out_of_bbox_share")
FEEDS = {
    "trip_updates.bus": "bus_tu",
    "trip_updates.subway": "subway_tu",
    "vehicle_positions.bus": "bus_vp",
}
MISSED_POLL_FACTOR = 1.5  # a fetch gap this many times the median = a poll with no new snapshot
STALE_FIX_S = 120
JUMP_DISTANCE_M = 200
JUMP_SPEED_MPS = 30  # 108 km/h
BBOX = {"lat": (40.4, 41.0), "lon": (-74.3, -73.6)}  # NYC service area


def local_day(seconds: Column) -> Column:
    return F.date_format(F.from_utc_timestamp(F.timestamp_seconds(seconds), TIMEZONE), "yyyyMMdd")


def p99(column: Column) -> Column:
    """Linear-interpolation 99th percentile, as in the golden quantile_cont."""
    return F.percentile(column, F.lit(0.99))


def long_form(
    frame: DataFrame, feed: Column | str, day: Column | str, metrics: tuple[str, ...]
) -> DataFrame:
    """Wide metric columns -> rows (feed, day, metric, value)."""
    pairs = ", ".join(f"'{m}', CAST({m} AS DOUBLE)" for m in metrics)
    return frame.select(
        F.col(feed) if isinstance(feed, str) else feed.alias("feed"),
        F.col(day) if isinstance(day, str) else day.alias("day"),
        F.expr(f"stack({len(metrics)}, {pairs}) AS (metric, value)"),
    )


def snapshot_metrics(snapshots: DataFrame) -> DataFrame:
    stats = (
        snapshots.select(
            F.col("feed").alias("source_feed"),
            F.col("feed_timestamp").cast("long").alias("ts"),
            "fetch_timestamp_us",
        )
        .groupBy("source_feed", "ts")
        .agg(F.max("fetch_timestamp_us").alias("fetch_us"))
        .select(
            F.element_at(
                F.create_map(*[F.lit(x) for kv in FEEDS.items() for x in kv]), F.col("source_feed")
            ).alias("feed"),
            "ts",
            (F.col("fetch_us") / 1_000_000).alias("fetched"),
        )
        .withColumn("header_lag_s", F.col("fetched") - F.col("ts"))
    )
    by_ts = Window.partitionBy("feed").orderBy("ts")
    # Nulls (a snapshot without a fetch time) sort last, as in the golden SQL.
    by_fetch = Window.partitionBy("feed").orderBy(F.col("fetched").asc_nulls_last(), "ts")
    snaps = stats.withColumn("gap_s", F.col("ts") - F.lag("ts").over(by_ts)).withColumn(
        "fetch_gap_s", F.col("fetched") - F.lag("fetched").over(by_fetch)
    )
    poll = snaps.groupBy("feed").agg(F.median("fetch_gap_s").alias("median_fetch_gap_s"))
    missed = F.col("fetch_gap_s") > MISSED_POLL_FACTOR * F.col("median_fetch_gap_s")
    day = (
        snaps.join(poll, "feed")
        .groupBy("feed", local_day(F.col("ts")).alias("day"))
        .agg(
            F.max("gap_s").cast("double").alias("max_gap_s"),
            (F.sum(missed.cast("long")) / F.count("fetch_gap_s")).alias("missed_poll_share"),
            p99(F.col("header_lag_s")).alias("header_lag_p99_s"),
        )
    )
    return long_form(day, "feed", "day", SNAPSHOT_METRICS)


def fixes(positions: DataFrame) -> DataFrame:
    return (
        positions.where(
            F.col("vehicle_id").isNotNull()
            & (F.col("vehicle_id") != "")
            & F.col("timestamp").isNotNull()
            & F.col("latitude").isNotNull()
            & F.col("longitude").isNotNull()
        )
        .select(
            "vehicle_id",
            F.col("feed_timestamp").cast("long").alias("feed_ts"),
            F.col("timestamp").cast("long").alias("ts"),
            F.col("latitude").cast("double").alias("lat"),
            F.col("longitude").cast("double").alias("lon"),
        )
        .distinct()
    )


def fix_steps(fix: DataFrame) -> DataFrame:
    """Steps between consecutive fixes of a vehicle; a republished fix counts once (first copy)."""
    first = (
        fix.groupBy("vehicle_id", "ts")
        .agg(F.min(F.struct("feed_ts", "lat", "lon")).alias("first"))
        .select("vehicle_id", "ts", "first.feed_ts", "first.lat", "first.lon")
    )
    w = Window.partitionBy("vehicle_id").orderBy("ts")
    steps = (
        first.withColumn("prev_ts", F.lag("ts").over(w))
        .withColumn("prev_lat", F.lag("lat").over(w))
        .withColumn("prev_lon", F.lag("lon").over(w))
        .where(F.col("prev_ts").isNotNull() & (F.col("ts") > F.col("prev_ts")))
    )
    dy = (F.col("lat") - F.col("prev_lat")) * METRES_PER_DEGREE
    dx = (F.col("lon") - F.col("prev_lon")) * METRES_PER_DEGREE * F.cos(F.radians("lat"))
    distance = F.sqrt(dy * dy + dx * dx)
    measured = steps.withColumn("distance_m", distance)
    speed = F.col("distance_m") / (F.col("ts") - F.col("prev_ts"))
    return measured.select(
        local_day(F.col("feed_ts")).alias("day"),
        "vehicle_id",
        "prev_ts",
        "ts",
        "distance_m",
        ((F.col("distance_m") > JUMP_DISTANCE_M) & (speed > JUMP_SPEED_MPS)).alias("jump"),
    )


def position_jumps(steps: DataFrame, dates: list[str]) -> DataFrame:
    return steps.where(F.col("jump") & F.col("day").isin(dates)).select(
        "day",
        "vehicle_id",
        "prev_ts",
        "ts",
        F.round("distance_m").alias("distance_m"),
        F.round(F.col("distance_m") / (F.col("ts") - F.col("prev_ts")), 1).alias("speed_mps"),
    )


def position_metrics(fix: DataFrame, steps: DataFrame) -> DataFrame:
    lat, lon = F.col("lat"), F.col("lon")
    outside = ~lat.between(*BBOX["lat"]) | ~lon.between(*BBOX["lon"])
    age = F.col("feed_ts") - F.col("ts")
    day = fix.groupBy(local_day(F.col("feed_ts")).alias("day")).agg(
        p99(age).alias("fix_age_p99_s"),
        F.avg((age > STALE_FIX_S).cast("int")).alias("stale_fix_share"),
        F.avg(outside.cast("int")).alias("out_of_bbox_share"),
    )
    jumps = steps.groupBy("day").agg(F.avg(F.col("jump").cast("int")).alias("jump_share"))
    feed = F.lit("bus_vp").alias("feed")
    return long_form(
        day, feed, "day", ("fix_age_p99_s", "stale_fix_share", "out_of_bbox_share")
    ).unionByName(long_form(jumps, feed, "day", ("jump_share",)))


def trip_update_metrics(
    observed: DataFrame,
    known_stops: DataFrame,
    match_summary: DataFrame,
    status_summary: DataFrame,
    missing_summary: DataFrame,
    ambiguous_summary: DataFrame,
) -> DataFrame:
    feed = F.concat(F.col("grp"), F.lit("_tu")).alias("feed")
    day = F.col("service_date").alias("day")
    unknown_stop = (
        observed.join(known_stops.withColumn("known", F.lit(True)), ["grp", "stop_id"], "left")
        .groupBy("grp", "service_date")
        .agg(F.avg(F.col("known").isNull().cast("int")).alias("unknown_stop_share"))
    )
    unknown_trip = match_summary.groupBy("grp", "service_date").agg(
        (
            F.coalesce(F.sum(F.when(F.col("tier") == "unscheduled", F.col("rt_trips"))), F.lit(0))
            / F.sum("rt_trips")
        ).alias("unknown_trip_share")
    )
    stuck = status_summary.groupBy("grp", "service_date").agg(
        (
            F.coalesce(F.sum(F.when(F.col("status") == "stale", F.col("events"))), F.lit(0))
            / F.sum("events")
        ).alias("stuck_share")
    )
    observable = F.col("scheduled") - F.col("unknown")
    not_run = missing_summary.select(
        "grp",
        "service_date",
        (F.col("not_run") / F.when(observable != 0, observable)).alias("not_run_share"),
    )
    ambiguous = ambiguous_summary.select(
        "grp",
        "service_date",
        (F.col("ambiguous_trip_stops") / F.col("trip_stops")).alias("ambiguous_share"),
    )
    parts = [
        (unknown_stop, "unknown_stop_share"),
        (unknown_trip, "unknown_trip_share"),
        (stuck, "stuck_share"),
        (not_run, "not_run_share"),
        (ambiguous, "ambiguous_share"),
    ]
    frames = [long_form(frame, feed, day, (metric,)) for frame, metric in parts]
    union = frames[0]
    for frame in frames[1:]:
        union = union.unionByName(frame)
    return union


def checks(spark: SparkSession, dates: list[str]) -> DataFrame:
    """Every applicable (feed, metric) on every service day, with its threshold."""
    rows = [
        (feed, metric, THRESHOLDS[metric], day)
        for feed in ("bus_tu", "subway_tu", "bus_vp")
        for metric in THRESHOLDS
        if metric in SNAPSHOT_METRICS
        or (feed.endswith("_tu") and metric in TRIP_UPDATE_METRICS)
        or (feed == "bus_vp" and metric in POSITION_METRICS)
        for day in dates
    ]
    return spark.createDataFrame(rows, "feed string, metric string, threshold double, day string")


def feed_quality_metrics(all_checks: DataFrame, values: DataFrame) -> DataFrame:
    value = F.round(F.col("value"), 6)
    return all_checks.join(values, ["feed", "metric", "day"], "left").select(
        "feed",
        "day",
        "metric",
        value.alias("value"),
        "threshold",
        F.coalesce(value <= F.col("threshold"), F.lit(False)).alias("passed"),
    )


def feed_quality_score(metrics: DataFrame) -> DataFrame:
    failed = F.sort_array(F.collect_list(F.when(~F.col("passed"), F.col("metric"))))
    return metrics.groupBy("feed", "day").agg(
        F.count("*").alias("checks"),
        F.sum(F.col("passed").cast("long")).alias("passed"),
        F.round(100 * F.sum(F.col("passed").cast("long")) / F.count("*"), 1).alias("score"),
        F.when(F.size(failed) > 0, F.array_join(failed, ", ")).alias("failed_checks"),
    )
