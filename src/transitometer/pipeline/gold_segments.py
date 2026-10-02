"""Gold BR4: segment travel times and delay attribution.

Definitions follow golden/sql/09_segments.sql, implemented here with the Spark DataFrame API,
independently of that SQL.

A segment joins two consecutive observed KPI events of one scheduled trip recorded by the same
vehicle, in stop order; no segment crosses a vehicle hand-off, because two vehicles' clocks and
predictions do not line up:
  observed_travel = arrival at the later stop - arrival at the earlier stop
  sched_travel    = the same difference in the timetable
  excess          = observed_travel - sched_travel (negative = time gained)
Arrivals are arrival-to-arrival, so a segment includes the dwell at its first stop (the feed has
no departures). Attribution per trip and vehicle is exact: final delay = delay inherited at the
first observed stop + the sum of the segment excesses.
"""

from __future__ import annotations

from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F

from transitometer.pipeline.gold_scorecards import quantile_disc


def sched_positions(stops: DataFrame) -> DataFrame:
    """1-based position of every scheduled stop within its trip (timetable stop order)."""
    trip = ["grp", "service_date", "trip_id"]
    return stops.select(
        *trip,
        "stop_sequence",
        F.row_number().over(Window.partitionBy(*trip).orderBy("stop_sequence")).alias("pos"),
    ).withColumnRenamed("trip_id", "static_trip_id")


def segments(stop_events: DataFrame, stops: DataFrame) -> DataFrame:
    events = stop_events.join(
        sched_positions(stops), ["grp", "service_date", "static_trip_id", "stop_sequence"]
    )
    w = Window.partitionBy("grp", "service_date", "static_trip_id", "unit").orderBy("stop_sequence")
    paired = events.select(
        "*",
        F.lag("stop_id").over(w).alias("from_stop"),
        F.lag("pos").over(w).alias("from_pos"),
        F.lag("sched_arrival").over(w).alias("from_sched"),
        F.lag("observed_arrival").over(w).alias("from_observed"),
        F.lag("delay_s").over(w).alias("from_delay"),
        F.lag("service_hour").over(w).alias("from_hour"),
    ).where(F.col("from_stop").isNotNull())
    sched_travel = F.col("sched_arrival") - F.col("from_sched")
    observed_travel = F.col("observed_arrival") - F.col("from_observed")
    return paired.select(
        "grp",
        "service_date",
        "static_trip_id",
        "unit",
        "route_id",
        "direction_id",
        "from_stop",
        F.col("stop_id").alias("to_stop"),
        (F.col("pos") - F.col("from_pos")).cast("long").alias("hops"),
        F.col("from_hour").alias("service_hour"),
        sched_travel.alias("sched_travel_s"),
        observed_travel.alias("observed_travel_s"),
        (observed_travel - sched_travel).alias("excess_s"),
        "from_delay",
        F.col("delay_s").alias("to_delay"),
    )


def trip_delay_attribution(stop_events: DataFrame, segs: DataFrame) -> DataFrame:
    keys = ["grp", "service_date", "static_trip_id", "unit"]
    ends = stop_events.groupBy(*keys).agg(
        F.min("route_id").alias("route_id"),
        F.count("*").alias("observed_stops"),
        F.min_by("delay_s", "stop_sequence").alias("inherited_delay_s"),
        F.max_by("delay_s", "stop_sequence").alias("final_delay_s"),
    )
    gained = segs.groupBy(*keys).agg(F.sum("excess_s").cast("long").alias("gained_delay_s"))
    return ends.join(gained, keys, "left").withColumn(
        "gained_delay_s", F.coalesce("gained_delay_s", F.lit(0)).cast("long")
    )


def delay_attribution_summary(attribution: DataFrame) -> DataFrame:
    mismatch = F.col("final_delay_s") != F.col("inherited_delay_s") + F.col("gained_delay_s")
    return attribution.groupBy("grp", "service_date").agg(
        F.count("*").alias("trip_vehicles"),
        F.round(F.avg("inherited_delay_s"), 1).alias("mean_inherited_delay_s"),
        F.round(F.avg("gained_delay_s"), 1).alias("mean_gained_delay_s"),
        F.round(F.avg("final_delay_s"), 1).alias("mean_final_delay_s"),
        F.sum(mismatch.cast("long")).alias("attribution_mismatches"),
    )


def segment_travel_stats(segs: DataFrame) -> DataFrame:
    """Travel-time distribution per adjacent segment and hour, pooled over the service days."""
    adjacent = segs.where((F.col("hops") == 1) & (F.col("observed_travel_s") > 0))
    return adjacent.groupBy(
        "grp", "route_id", "direction_id", "from_stop", "to_stop", "service_hour"
    ).agg(
        F.count("*").alias("segments"),
        F.median("sched_travel_s").cast("double").alias("sched_travel_s"),
        quantile_disc("observed_travel_s", 0.1).alias("p10_travel_s"),
        quantile_disc("observed_travel_s", 0.5).alias("p50_travel_s"),
        quantile_disc("observed_travel_s", 0.9).alias("p90_travel_s"),
        quantile_disc("excess_s", 0.5).alias("median_excess_s"),
    )
