"""Gold BR3 delivery: bus arrivals at the last stop, then promised vs delivered scheduled trips.

Definitions follow golden/sql/07_terminals.sql and 08_missing_trips.sql, implemented here with
the Spark DataFrame API, independently of that SQL.

Terminal arrivals (bus only; the subway feed has no vehicle positions): trip updates cannot place
the arrival at the last stop, because that stop only leaves the update list when the trip leaves
the feed. The arrival is the first GPS fix of the vehicle, still reporting the trip, within
TERMINAL_RADIUS_M of the last stop, at or after the vehicle's last passed stop on the trip.

Trip delivery: every scheduled trip on a route the feed carries that day gets one class, checked
in this order: delivered, unknown (span outside the snapshots read or overlapping a feed outage),
missing (never reported), not_run (reported, but no stop passed and no terminal arrival), partial.
"""

from __future__ import annotations

from pyspark.sql import Column, DataFrame, Window
from pyspark.sql import functions as F

TERMINAL_RADIUS_M = 50
METRES_PER_DEGREE = 111320  # equirectangular distance: exact enough within a city at 50 m
OUTAGE_GAP_S = 300  # a snapshot gap longer than this makes overlapping trips 'unknown'
PARTIAL_SHARE = 0.5  # fewer passed intermediate stops than this share of them = partial


def sched_bounds(stops: DataFrame) -> DataFrame:
    return stops.groupBy("grp", "service_date", "trip_id").agg(
        F.min("stop_sequence").alias("first_seq"), F.max("stop_sequence").alias("last_seq")
    )


def stop_geo(bus_stops: DataFrame) -> DataFrame:
    """One coordinate pair per stop id; a single row's pair when timetable versions disagree."""
    pos = F.min(F.struct(F.col("lat"), F.col("lon")))
    return (
        bus_stops.where(F.col("lat").isNotNull() & F.col("lon").isNotNull())
        .groupBy("stop_id")
        .agg(pos.alias("pos"))
        .select("stop_id", F.col("pos.lat").alias("lat"), F.col("pos.lon").alias("lon"))
    )


def within(
    lat: Column, lon: Column, target_lat: Column, target_lon: Column, metres: float
) -> Column:
    dy = (lat - target_lat) * METRES_PER_DEGREE
    dx = (lon - target_lon) * METRES_PER_DEGREE * F.cos(F.radians(target_lat))
    return dy * dy + dx * dx <= metres * metres


def terminal_targets(matched: DataFrame, stops: DataFrame, geo: DataFrame) -> DataFrame:
    bounds = sched_bounds(stops)
    last = stops.join(bounds, ["grp", "service_date", "trip_id"]).where(
        F.col("stop_sequence") == F.col("last_seq")
    )
    return (
        matched.where(F.col("grp") == "bus")
        .join(
            last.withColumnRenamed("trip_id", "static_trip_id"),
            ["grp", "service_date", "static_trip_id"],
        )
        .join(geo, "stop_id")
        .select(
            "grp",
            "service_date",
            "trip_id",
            "static_trip_id",
            "route_id",
            "stop_id",
            "sched_arrival",
            "base",
            "lat",
            "lon",
        )
    )


def terminal_candidates(
    targets: DataFrame, observed: DataFrame, positions: DataFrame, dates: list[str]
) -> DataFrame:
    """Per target and vehicle: the first qualifying fix near the last stop."""
    last_pass = (
        observed.where((F.col("grp") == "bus") & (F.col("status") == "passed"))
        .groupBy("trip_id", "service_date", "unit")
        .agg(F.max("last_prediction").alias("last_passed"))
    )
    fixes = positions.where(
        F.col("trip_id").isNotNull()
        & F.col("vehicle_id").isNotNull()
        & (F.col("vehicle_id") != "")
        & F.col("latitude").isNotNull()
        & F.col("longitude").isNotNull()
        & F.col("start_date").isin(dates)
    ).select(
        "trip_id",
        F.col("start_date").alias("service_date"),
        F.col("vehicle_id").alias("unit"),
        F.coalesce(F.col("timestamp"), F.col("feed_timestamp")).cast("long").alias("ts"),
        F.col("latitude").cast("double").alias("fix_lat"),
        F.col("longitude").cast("double").alias("fix_lon"),
    )
    return (
        targets.join(fixes, ["trip_id", "service_date"])
        .join(last_pass, ["trip_id", "service_date", "unit"])
        .where(F.col("ts") >= F.col("last_passed"))
        .where(
            within(
                F.col("fix_lat"), F.col("fix_lon"), F.col("lat"), F.col("lon"), TERMINAL_RADIUS_M
            )
        )
        .groupBy(
            "grp",
            "service_date",
            "trip_id",
            "static_trip_id",
            "route_id",
            "stop_id",
            "sched_arrival",
            "base",
            "unit",
        )
        .agg(F.min("ts").alias("observed_arrival"))
    )


def terminal_events(candidates: DataFrame) -> DataFrame:
    trip = Window.partitionBy("grp", "service_date", "static_trip_id")
    first = trip.orderBy("observed_arrival", "unit", "trip_id")
    return (
        candidates.withColumn("observations", F.count("*").over(trip).cast("long"))
        .withColumn("rank", F.row_number().over(first))
        .where(F.col("rank") == 1)
        .select(
            "grp",
            "service_date",
            "static_trip_id",
            "trip_id",
            "unit",
            "route_id",
            "stop_id",
            "sched_arrival",
            "observed_arrival",
            (F.col("observed_arrival") - F.col("sched_arrival")).alias("delay_s"),
            F.floor((F.col("sched_arrival") - F.col("base")) / 3600)
            .cast("long")
            .alias("service_hour"),
            "observations",
        )
    )


def terminal_summary(targets: DataFrame, events: DataFrame) -> DataFrame:
    trips = targets.select("grp", "service_date", "static_trip_id").distinct()
    single = F.col("observations") == 1
    joined = trips.join(
        events.select("grp", "service_date", "static_trip_id", "observations", "delay_s"),
        ["grp", "service_date", "static_trip_id"],
        "left",
    )
    measured = F.sum(single.cast("long"))
    return joined.groupBy("grp", "service_date").agg(
        F.count("*").alias("matched_trips"),
        F.coalesce(measured, F.lit(0)).alias("measured"),
        F.coalesce(F.sum((F.col("observations") > 1).cast("long")), F.lit(0)).alias("ambiguous"),
        F.round(F.coalesce(measured, F.lit(0)) / F.count("*"), 4).alias("measured_share"),
        F.median(F.when(single, F.col("delay_s"))).cast("double").alias("median_delay_s"),
    )


def snapshot_times(snapshots: DataFrame) -> DataFrame:
    """Distinct trip-update snapshot times per mode (the archive's feed timestamps)."""
    grp = F.when(F.col("feed") == "trip_updates.bus", "bus").when(
        F.col("feed") == "trip_updates.subway", "subway"
    )
    return (
        snapshots.select(grp.alias("grp"), F.col("feed_timestamp").cast("long").alias("ts"))
        .where(F.col("grp").isNotNull())
        .distinct()
    )


def trip_delivery(
    stops: DataFrame,
    active_trips: DataFrame,
    matched: DataFrame,
    trip_stops: DataFrame,
    candidates: DataFrame,
    snapshots: DataFrame,
) -> DataFrame:
    bounds = sched_bounds(stops)
    intermediate = ~F.col("stop_sequence").isin(F.col("first_seq"), F.col("last_seq"))
    spans = (
        stops.join(bounds, ["grp", "service_date", "trip_id"])
        .groupBy("grp", "service_date", "trip_id")
        .agg(
            F.min("route_id").alias("route_id"),
            F.min("direction_id").alias("direction_id"),
            F.min("sched_arrival").alias("sched_start"),
            F.max("sched_arrival").alias("sched_end"),
            F.count_distinct(F.when(intermediate, F.col("stop_id"))).alias("intermediate_stops"),
            F.min("base").alias("base"),
        )
    )
    feed_routes = (
        matched.join(
            active_trips.withColumnRenamed("trip_id", "static_trip_id"),
            ["grp", "service_date", "static_trip_id"],
        )
        .select("grp", "service_date", "route_id")
        .distinct()
    )
    reported = (
        matched.select("grp", "service_date", F.col("static_trip_id").alias("trip_id"))
        .distinct()
        .withColumn("reported", F.lit(True))
    )
    passed = trip_stops.groupBy(
        "grp", "service_date", F.col("static_trip_id").alias("trip_id")
    ).agg(F.count_distinct("stop_id").alias("passed_stops"))
    arrived = (
        candidates.select("grp", "service_date", F.col("static_trip_id").alias("trip_id"))
        .distinct()
        .withColumn("arrived", F.lit(True))
    )
    times = snapshot_times(snapshots)
    coverage = times.groupBy("grp").agg(
        F.min("ts").alias("first_snapshot"), F.max("ts").alias("last_snapshot")
    )
    previous = F.lag("ts").over(Window.partitionBy("grp").orderBy("ts"))
    outages = (
        times.withColumn("gap_start", previous)
        .where(F.col("ts") - F.col("gap_start") > OUTAGE_GAP_S)
        .select("grp", "gap_start", F.col("ts").alias("gap_end"))
    )
    trip_key = ["grp", "service_date", "trip_id"]
    flagged = (
        spans.join(feed_routes, ["grp", "service_date", "route_id"])
        .join(coverage, "grp")
        .join(reported, trip_key, "left")
        .join(passed, trip_key, "left")
        .join(arrived, trip_key, "left")
        .withColumn("reported", F.coalesce("reported", F.lit(False)))
        .withColumn("arrived", F.coalesce("arrived", F.lit(False)))
        .withColumn("passed_stops", F.coalesce("passed_stops", F.lit(0)).cast("long"))
    )
    overlapping = (
        flagged.alias("s")
        .join(
            outages.alias("o"),
            (F.col("o.grp") == F.col("s.grp"))
            & (F.col("o.gap_start") < F.col("s.sched_end"))
            & (F.col("o.gap_end") > F.col("s.sched_start")),
        )
        .select("s.grp", "s.service_date", "s.trip_id")
        .distinct()
        .withColumn("in_outage", F.lit(True))
    )
    flagged = flagged.join(overlapping, trip_key, "left")
    unobservable = (
        (F.col("sched_start") < F.col("first_snapshot"))
        | (F.col("sched_end") > F.col("last_snapshot"))
        | F.coalesce(F.col("in_outage"), F.lit(False))
    )
    delivery = (
        F.when(
            F.col("reported")
            & (F.col("passed_stops") >= PARTIAL_SHARE * F.col("intermediate_stops")),
            "delivered",
        )
        .when(unobservable, "unknown")
        .when(~F.col("reported"), "missing")
        .when((F.col("passed_stops") == 0) & ~F.col("arrived"), "not_run")
        .otherwise("partial")
    )
    return flagged.select(
        "grp",
        "service_date",
        "trip_id",
        "route_id",
        "direction_id",
        "sched_start",
        "sched_end",
        F.floor((F.col("sched_start") - F.col("base")) / 3600).cast("long").alias("service_hour"),
        F.col("intermediate_stops").cast("long").alias("intermediate_stops"),
        "passed_stops",
        "reported",
        "arrived",
        delivery.alias("delivery"),
    )


def delivery_counts(delivery: DataFrame, *keys: str) -> DataFrame:
    """Scheduled trips per delivery class, with missing and not-delivered shares."""

    def count(*classes: str) -> Column:
        return F.sum(F.col("delivery").isin(*classes).cast("long"))

    known = F.sum((F.col("delivery") != "unknown").cast("long"))
    known = F.when(known != 0, known)
    return delivery.groupBy(*keys).agg(
        F.count("*").alias("scheduled"),
        count("delivered").alias("delivered"),
        count("partial").alias("partial"),
        count("missing").alias("missing"),
        count("not_run").alias("not_run"),
        count("unknown").alias("unknown"),
        F.round(count("missing") / known, 4).alias("missing_share"),
        F.round(count("missing", "not_run") / known, 4).alias("not_delivered_share"),
    )
