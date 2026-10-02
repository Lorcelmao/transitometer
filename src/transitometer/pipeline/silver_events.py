"""Silver stop events: decoded trip-update rows + the static timetable -> observed stop arrivals.

Batch job over the Silver tables written by silver_ingest. It implements the stop-event rules
documented in golden/sql/01–04 with the Spark DataFrame API, independently of that SQL, so the
golden comparison checks two implementations of one specification:

  scheduled_stops   timetable stop times of every trip active on each service day
  observed_events   per reporting unit and stop: last prediction while listed + status
  matched_trips     real-time trip -> scheduled trip (exact, suffix, route_direction tiers)
  stop_events       one observed arrival per scheduled intermediate trip-stop, with its delay
  + summaries       event_status_summary, trip_match_summary, ambiguous_summary

Rule summary (see golden/sql/02_stop_events.sql for the full rationale):
  A trip update lists the stops a vehicle has not served yet. When a stop drops out of the list
  while the trip is still reported, it was served, and the prediction in the last snapshot that
  listed it is the observed arrival. Inference runs per reporting unit (vehicle_id, else the trip).

Usage: spark-submit silver_events.py --service-dates 20260922 20260923
           --schedule bus=/data/landing/schedules/... --schedule subway=... [--prefix rt]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from pyspark.sql import Column, DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from transitometer.pipeline.layout import lakehouse_root
from transitometer.pipeline.service_days import WEEKDAYS, day_base, weekday

MAX_LEAD_S = 180  # a stop that dropped out with a prediction this far ahead was not served
MAX_STALE_S = 90  # a prediction this far in the past while listed is a timetable echo
TERMINAL_GRACE_S = 300  # final stop: prediction vs the trip's last snapshot
SUBWAY_AFTER_MIDNIGHT = 144000  # NYCT trip ids start with the origin time in 1/100 minutes
EPOCH_LIMIT = 10_000_000_000  # predictions outside (0, this) are not epoch seconds
STATIC_TABLES = {
    "calendar": [
        "service_id",
        "start_date",
        "end_date",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ],
    "calendar_dates": ["service_id", "date", "exception_type"],
    "trips": ["trip_id", "route_id", "direction_id", "service_id"],
    "stop_times": [
        "trip_id",
        "arrival_time",
        "departure_time",
        "stop_id",
        "stop_sequence",
        "timepoint",
    ],
}


def _try_cast(col: Column, sql_type: str) -> Column:
    """The value as sql_type, or NULL when it does not parse (ANSI mode would raise)."""
    return col.try_cast(sql_type)


def static_table(spark: SparkSession, group: str, dirs: list[str], table: str) -> DataFrame:
    """One static GTFS table over every timetable version of a group, all columns as strings.

    Versions differ in column sets and types, so each file is read on its own and aligned.
    """
    wanted = STATIC_TABLES[table]
    frames = []
    for folder in dirs:
        frame = spark.read.parquet(f"{folder}/{table}.parquet")
        present = set(frame.columns)
        frames.append(
            frame.select(
                *[
                    (F.col(c).cast("string") if c in present else F.lit(None).cast("string")).alias(
                        c
                    )
                    for c in wanted
                ]
            )
        )
    union = frames[0]
    for frame in frames[1:]:
        union = union.unionByName(frame)
    return union.withColumn("grp", F.lit(group))


def timetable(
    spark: SparkSession, schedules: dict[str, list[str]], dates: list[str]
) -> tuple[DataFrame, DataFrame]:
    """(active_trips, scheduled_stops) for every service day, over all timetable versions."""
    days = spark.createDataFrame(
        [(d, day_base(d), weekday(d)) for d in dates], "service_date string, base long, wd string"
    )
    trip_frames, stop_frames = [], []
    for group, dirs in schedules.items():
        calendar = static_table(spark, group, dirs, "calendar")
        regular = (
            calendar.crossJoin(days)
            .where(
                (F.col("start_date") <= F.col("service_date"))
                & (F.col("end_date") >= F.col("service_date"))
            )
            .where(
                F.coalesce(
                    *[F.when(F.col("wd") == day, _try_cast(F.col(day), "INT")) for day in WEEKDAYS]
                )
                == 1
            )
            .select("grp", "service_date", "service_id")
        )
        exceptions = static_table(spark, group, dirs, "calendar_dates").join(
            days, F.col("date") == F.col("service_date")
        )
        added = exceptions.where(_try_cast(F.col("exception_type"), "INT") == 1)
        removed = exceptions.where(_try_cast(F.col("exception_type"), "INT") == 2)
        active_services = (
            regular.union(added.select("grp", "service_date", "service_id"))
            .distinct()
            .join(
                removed.select("grp", "service_date", "service_id"),
                ["grp", "service_date", "service_id"],
                "left_anti",
            )
        )
        trips = static_table(spark, group, dirs, "trips").join(
            active_services, ["grp", "service_id"]
        )
        active_trips = trips.select(
            "grp",
            "service_date",
            "trip_id",
            "route_id",
            _try_cast(F.col("direction_id"), "INT").alias("direction_id"),
        )
        trip_frames.append(active_trips)
        stop_times = static_table(spark, group, dirs, "stop_times").withColumn(
            "time", F.coalesce("arrival_time", "departure_time")
        )
        hms = F.split("time", ":")
        seconds = (
            _try_cast(hms[0], "BIGINT") * 3600
            + _try_cast(hms[1], "BIGINT") * 60
            + _try_cast(hms[2], "BIGINT")
        )
        stop_frames.append(
            stop_times.where(F.col("time").isNotNull())
            .join(active_trips, ["grp", "trip_id"])
            .join(days.select("service_date", "base"), "service_date")
            .select(
                "grp",
                "service_date",
                "trip_id",
                "route_id",
                "direction_id",
                "stop_id",
                _try_cast(F.col("stop_sequence"), "INT").alias("stop_sequence"),
                (F.coalesce(_try_cast(F.col("timepoint"), "INT"), F.lit(0)) == 1).alias(
                    "timepoint"
                ),
                (F.col("base") + seconds).alias("sched_arrival"),
                "base",
            )
        )
    return _union(trip_frames), _union(stop_frames)


def _union(frames: list[DataFrame]) -> DataFrame:
    union = frames[0]
    for frame in frames[1:]:
        union = union.unionByName(frame)
    return union


def static_stops(spark: SparkSession, schedules: dict[str, list[str]]) -> DataFrame:
    """Every stop id of every timetable version, with its name and coordinates as published."""
    frames = []
    for group, dirs in schedules.items():
        for folder in dirs:
            frame = spark.read.parquet(f"{folder}/stops.parquet")
            frames.append(
                frame.select(
                    F.lit(group).alias("grp"),
                    F.col("stop_id").cast("string").alias("stop_id"),
                    F.col("stop_lat").cast("double").alias("lat"),
                    F.col("stop_lon").cast("double").alias("lon"),
                    (
                        F.col("stop_name").cast("string")
                        if "stop_name" in frame.columns
                        else F.lit(None).cast("string")
                    ).alias("stop_name"),
                )
            )
    return _union(frames)


def trip_update_rows(spark: SparkSession, silver: str, dates: list[str]) -> DataFrame:
    """Bus and subway stop rows reduced to what inference needs, on their service day."""

    def rows(group: str) -> DataFrame:
        frame = spark.read.format("delta").load(f"{silver}/trip_update_rows/{group}")
        service_date = F.col("start_date")
        if group == "subway":
            origin = _try_cast(F.split("trip_id", "_")[0], "INT")
            previous = F.date_format(
                F.date_sub(F.expr("try_to_date(start_date, 'yyyyMMdd')"), 1), "yyyyMMdd"
            )
            service_date = F.when(origin >= SUBWAY_AFTER_MIDNIGHT, previous).otherwise(
                F.col("start_date")
            )
        vehicle = F.when(F.col("vehicle_id") != "", F.col("vehicle_id"))
        return frame.select(
            F.lit(group).alias("grp"),
            "trip_id",
            service_date.alias("service_date"),
            "route_id",
            "stop_id",
            F.coalesce(vehicle, F.col("trip_id")).alias("unit"),
            F.coalesce("arrival_time", "departure_time").alias("predicted"),
            F.col("feed_timestamp").cast("long").alias("feed_timestamp"),
        )

    union = rows("bus").unionByName(rows("subway"))
    return union.where(
        F.col("trip_id").isNotNull()
        & (F.col("trip_id") != "")
        & F.col("stop_id").isNotNull()
        & (F.col("predicted") > 0)
        & (F.col("predicted") < EPOCH_LIMIT)
        & F.col("unit").isNotNull()
        & F.col("service_date").isin(dates)
    )


def observed_events(rows: DataFrame) -> DataFrame:
    unit_stop = ["grp", "trip_id", "service_date", "unit", "stop_id"]
    unit_trip = ["grp", "trip_id", "service_date", "unit"]
    # The latest snapshot wins; a duplicate row in that snapshot resolves to the later
    # prediction. Ordering structs field by field gives exactly that total order.
    stop_last = rows.groupBy(*unit_stop).agg(
        F.min("route_id").alias("rt_route_id"),
        F.min("feed_timestamp").alias("first_listed"),
        F.max("feed_timestamp").alias("last_listed"),
        F.max(F.struct("feed_timestamp", "predicted"))["predicted"].alias("last_prediction"),
    )
    trip_last = (
        stop_last.withColumn("trip_max", F.max("last_listed").over(Window.partitionBy(*unit_trip)))
        .groupBy(*unit_trip)
        .agg(
            F.max("last_listed").alias("trip_last_listed"),
            F.sum((F.col("last_listed") == F.col("trip_max")).cast("int")).alias(
                "stops_in_last_snapshot"
            ),
        )
    )
    s = stop_last.join(trip_last, unit_trip)
    served_later = F.col("last_listed") < F.col("trip_last_listed")
    status = (
        F.when(
            served_later & (F.col("last_prediction") - F.col("last_listed") > MAX_LEAD_S),
            "implausible",
        )
        .when(F.col("last_listed") - F.col("last_prediction") > MAX_STALE_S, "stale")
        .when(served_later, "passed")
        .when(
            (F.col("stops_in_last_snapshot") == 1)
            & (F.col("last_prediction") <= F.col("trip_last_listed") + TERMINAL_GRACE_S),
            "terminal",
        )
        .otherwise("unconfirmed")
    )
    return s.withColumn("status", status).drop("stops_in_last_snapshot")


def matched_trips(observed: DataFrame, active_trips: DataFrame) -> DataFrame:
    """Real-time trip -> unique active scheduled trip, by the first tier that matches.

    Keys come from every active trip row, not de-duplicated: a trip id listed twice (two
    timetable versions active the same day) is ambiguous and stays unmatched.
    """
    rt = observed.select("grp", "trip_id", "service_date").distinct()
    keys = active_trips.select("grp", "service_date", F.col("trip_id").alias("static_trip_id"))
    # NYCT static ids carry a prefix before the first "_" that real-time ids omit.
    keys = keys.withColumn(
        "suffix_key",
        F.when(
            F.instr("static_trip_id", "_") > 0,
            F.expr("substr(static_trip_id, instr(static_trip_id, '_') + 1)"),
        ),
    )

    def rd_key(column: str) -> Column:
        parts = F.split(F.col(column), r"\.\.", 2)
        return F.concat(parts[0], F.lit(".."), F.substring(parts[1], 1, 1))

    def unique(frame: DataFrame, key: Column) -> DataFrame:
        grouped = frame.withColumn("k", key).where(F.col("k").isNotNull())
        return (
            grouped.groupBy("grp", "service_date", "k")
            .agg(F.count("*").alias("n"), F.min("static_trip_id").alias("static_trip_id"))
            .where(F.col("n") == 1)
            .drop("n")
        )

    tiers = [
        ("exact", unique(keys, F.col("static_trip_id")), F.col("trip_id")),
        ("suffix", unique(keys, F.col("suffix_key")), F.col("trip_id")),
        (
            "route_direction",
            unique(keys.where(F.instr("suffix_key", "..") > 0), rd_key("suffix_key")),
            F.when(F.instr("trip_id", "..") > 0, rd_key("trip_id")),
        ),
    ]
    remaining, matched = rt, None
    for tier, table, rt_key in tiers:
        hits = (
            remaining.withColumn("k", rt_key)
            .join(table, ["grp", "service_date", "k"])
            .select("grp", "trip_id", "service_date", "static_trip_id", F.lit(tier).alias("tier"))
        )
        matched = hits if matched is None else matched.unionByName(hits)
        remaining = remaining.join(hits, ["grp", "trip_id", "service_date"], "left_anti")
    assert matched is not None
    return matched


def stop_events(observed: DataFrame, matched: DataFrame, stops: DataFrame) -> DataFrame:
    """One observation per scheduled intermediate trip-stop; ambiguous ones are flagged."""
    trip = ["grp", "service_date", "trip_id"]
    bounds = stops.groupBy(*trip).agg(
        F.min("stop_sequence").alias("first_seq"), F.max("stop_sequence").alias("last_seq")
    )
    visits = Window.partitionBy("grp", "service_date", "trip_id", "stop_id")
    sched = (
        stops.withColumn("visits", F.count("*").over(visits))
        .join(bounds, trip)
        .withColumnRenamed("trip_id", "static_trip_id")
    )
    candidates = (
        observed.where(F.col("status").isin("passed", "terminal"))
        .join(matched, ["grp", "trip_id", "service_date"])
        .join(sched, ["grp", "service_date", "static_trip_id", "stop_id"])
        .where(F.col("visits") == 1)
    )
    intermediate = candidates.where(
        (F.col("stop_sequence") != F.col("first_seq"))
        & (F.col("stop_sequence") != F.col("last_seq"))
        & (F.col("status") == "passed")
    )
    trip_stop = Window.partitionBy("grp", "service_date", "static_trip_id", "stop_id")
    first = trip_stop.orderBy("last_prediction", "unit", "trip_id")
    return (
        intermediate.withColumn("observations", F.count("*").over(trip_stop))
        .withColumn("rank", F.row_number().over(first))
        .where(F.col("rank") == 1)
        .select(
            "grp",
            "service_date",
            "trip_id",
            "unit",
            "static_trip_id",
            "tier",
            "route_id",
            "direction_id",
            "stop_id",
            "stop_sequence",
            "timepoint",
            "sched_arrival",
            F.col("last_prediction").alias("observed_arrival"),
            (F.col("last_prediction") - F.col("sched_arrival")).alias("delay_s"),
            F.floor((F.col("sched_arrival") - F.col("base")) / 3600)
            .cast("long")
            .alias("service_hour"),
            "status",
            F.col("observations").cast("long").alias("observations"),
        )
    )


def summaries(observed: DataFrame, matched: DataFrame, events: DataFrame) -> dict[str, DataFrame]:
    rt = observed.select("grp", "trip_id", "service_date").distinct()
    return {
        "event_status_summary": observed.groupBy("grp", "service_date", "status").agg(
            F.count("*").alias("events")
        ),
        "trip_match_summary": rt.join(matched, ["grp", "trip_id", "service_date"], "left")
        .withColumn("tier", F.coalesce("tier", F.lit("unscheduled")))
        .groupBy("grp", "service_date", "tier")
        .agg(F.count("*").alias("rt_trips")),
        "ambiguous_summary": events.groupBy("grp", "service_date").agg(
            F.count("*").alias("trip_stops"),
            F.sum((F.col("observations") > 1).cast("long")).alias("ambiguous_trip_stops"),
            F.round(F.avg((F.col("observations") > 1).cast("int")), 4).alias("ambiguous_share"),
        ),
    }


def build_session() -> SparkSession:
    return (
        SparkSession.builder.appName("transitometer-silver-events")
        .master(os.environ.get("SPARK_MASTER", "local[8]"))
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config(
            "spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog"
        )
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.parquet.compression.codec", "zstd")
        .getOrCreate()
    )


def write(frame: DataFrame, path: str, partition: str | None = None) -> int:
    writer = frame.write.format("delta").mode("overwrite").option("overwriteSchema", "true")
    if partition:
        writer = writer.partitionBy(partition)
    writer.save(path)
    count: int = frame.sparkSession.read.format("delta").load(path).count()
    return count


def progress(message: str) -> None:
    print(f"progress silver-events {message}", file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", default="rt")
    parser.add_argument("--service-dates", nargs="+", required=True)
    parser.add_argument("--schedule", action="append", required=True, help="group=folder")
    parser.add_argument("--lakehouse", default=os.environ.get("LAKEHOUSE_DIR", "/data/lakehouse"))
    args = parser.parse_args(argv)
    schedules: dict[str, list[str]] = {}
    for item in args.schedule:
        group, _, folder = item.partition("=")
        schedules.setdefault(group, []).append(folder)
    silver = lakehouse_root(args.lakehouse, args.prefix) + "/silver"
    spark = build_session()
    spark.sparkContext.setLogLevel("WARN")

    counts: dict[str, int] = {}
    progress("timetable")
    trips_frame, stops_frame = timetable(spark, schedules, args.service_dates)
    counts["active_trips"] = write(trips_frame, f"{silver}/active_trips")
    counts["scheduled_stops"] = write(stops_frame, f"{silver}/scheduled_stops")
    counts["static_stops"] = write(static_stops(spark, schedules), f"{silver}/static_stops")
    active_trips = spark.read.format("delta").load(f"{silver}/active_trips")
    stops = spark.read.format("delta").load(f"{silver}/scheduled_stops")
    progress("observed_events")
    observed_frame = observed_events(trip_update_rows(spark, silver, args.service_dates))
    counts["observed_events"] = write(observed_frame, f"{silver}/observed_events", "service_date")
    observed = spark.read.format("delta").load(f"{silver}/observed_events")
    progress("matched_trips")
    counts["matched_trips"] = write(
        matched_trips(observed, active_trips), f"{silver}/matched_trips"
    )
    matched = spark.read.format("delta").load(f"{silver}/matched_trips")
    progress("stop_events")
    counts["stop_events_with_ambiguous"] = write(
        stop_events(observed, matched, stops), f"{silver}/trip_stop_events", "service_date"
    )
    trip_stops = spark.read.format("delta").load(f"{silver}/trip_stop_events")
    counts["stop_events"] = write(
        trip_stops.where(F.col("observations") == 1), f"{silver}/stop_events", "service_date"
    )
    for name, frame in summaries(observed, matched, trip_stops).items():
        progress(name)
        counts[name] = write(frame, f"{silver}/{name}")
    spark.stop()
    print(json.dumps({"prefix": args.prefix, "service_dates": args.service_dates, "rows": counts}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
