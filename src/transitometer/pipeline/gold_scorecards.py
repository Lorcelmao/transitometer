"""Gold BR5 reliability scorecards with uncertainty, and BR8 stop-level departure reliability.

Definitions follow golden/sql/10_scorecards.sql, implemented here with the Spark DataFrame API,
independently of that SQL. Both pool the golden window; the statistic is the on-time share of
KPI stop events (the BR1 band).

Route and route-hour intervals: a Poisson bootstrap with the trip as resampling unit. In resample
b every trip gets weight ~ Poisson(1), drawn from the first 8 hex digits of
md5('<seed>|<b>|<grp>|<service_date>|<static_trip_id>') against the Poisson(1) CDF scaled to 2^32,
so every engine reproduces the weights exactly. CI = 2.5 / 97.5 % quantiles of the resampled
shares; route ranks (1 = best) get an interval from ranking within each resample.

Route-stop-hour (BR8): the closed-form 95 % Wilson score interval. Cells with fewer than
MIN_EVENTS events, and routes or route-hours with fewer than MIN_TRIPS trips, are insufficient;
only sufficient routes are ranked.
"""

from __future__ import annotations

from pyspark.sql import Column, DataFrame, SparkSession, Window
from pyspark.sql import functions as F

SEED = "transitometer"
RESAMPLES = 200
MIN_EVENTS = 10
MIN_TRIPS = 5
EARLY_S = 60
LATE_S = 300
# floor(F(k) * 2^32) for the Poisson(1) CDF, k = 0..7; a uniform u below the k-th bound -> k.
POISSON_BOUNDS = (
    1580030168,
    3160060337,
    3950075421,
    4213413783,
    4279248373,
    4292415291,
    4294609777,
    4294923276,
)
Z = 1.959963984540054  # 97.5 % normal quantile
Z2 = 3.841458820694124  # Z squared


def poisson1(u: Column) -> Column:
    weight = F.lit(len(POISSON_BOUNDS))
    for k, bound in reversed(list(enumerate(POISSON_BOUNDS))):
        weight = F.when(u < bound, k).otherwise(weight)
    return weight


def wilson(k: Column, n: Column, sign: int) -> Column:
    p = k / n
    centre = p + Z2 / (2 * n)
    spread = Z * F.sqrt(p * (1 - p) / n + Z2 / (4 * n * n))
    return (centre + sign * spread) / (1 + Z2 / n)


def quantile_disc(column: str, q: float) -> Column:
    """SQL-standard discrete quantile: the value at 1-based position max(1, ceil(n * q))."""
    values = F.sort_array(F.collect_list(column))
    return F.element_at(values, F.greatest(F.lit(1), F.ceil(F.size(values) * F.lit(q))).cast("int"))


def scored_events(stop_events: DataFrame) -> DataFrame:
    on_time = (F.col("delay_s") >= -EARLY_S) & (F.col("delay_s") <= LATE_S)
    return stop_events.select(
        "grp",
        "service_date",
        "static_trip_id",
        "route_id",
        "direction_id",
        "stop_id",
        "service_hour",
        "delay_s",
        on_time.cast("int").alias("on_time"),
    )


def bootstrap_weights(spark: SparkSession, events: DataFrame) -> DataFrame:
    trips = events.select("grp", "service_date", "static_trip_id").distinct()
    resamples = spark.range(1, RESAMPLES + 1).withColumnRenamed("id", "b")
    key = F.concat_ws(
        "|", F.lit(SEED), F.col("b").cast("string"), "grp", "service_date", "static_trip_id"
    )
    u = F.conv(F.substring(F.md5(key), 1, 8), 16, 10).cast("long")
    return trips.crossJoin(resamples).select(
        "grp", "service_date", "static_trip_id", "b", poisson1(u).alias("w")
    )


def _resampled(per_trip: DataFrame, weights: DataFrame, keys: list[str]) -> DataFrame:
    weighted = per_trip.join(weights, ["grp", "service_date", "static_trip_id"])
    return (
        weighted.groupBy(*keys, "b")
        .agg(
            F.sum(F.col("w") * F.col("k")).alias("wk"),
            F.sum(F.col("w") * F.col("n")).alias("wn"),
        )
        .where(F.col("wn") > 0)
        .select(*keys, "b", (F.col("wk") / F.col("wn")).alias("share"))
    )


def route_scorecard(events: DataFrame, weights: DataFrame) -> DataFrame:
    per_trip = events.groupBy("grp", "route_id", "service_date", "static_trip_id").agg(
        F.count("*").alias("n"), F.sum("on_time").cast("long").alias("k")
    )
    point = per_trip.groupBy("grp", "route_id").agg(
        F.sum("n").cast("long").alias("events"),
        F.count("*").alias("trips"),
        F.sum("k").cast("long").alias("on_time"),
    )
    sufficient = (F.col("events") >= MIN_EVENTS) & (F.col("trips") >= MIN_TRIPS)
    resampled = _resampled(per_trip, weights, ["grp", "route_id"])
    ci = resampled.groupBy("grp", "route_id").agg(
        F.percentile("share", F.lit(0.025)).alias("lo"),
        F.percentile("share", F.lit(0.975)).alias("hi"),
    )
    ranked = (
        resampled.join(point.where(sufficient).select("grp", "route_id"), ["grp", "route_id"])
        .withColumn(
            "rank_b",
            F.rank().over(Window.partitionBy("grp", "b").orderBy(F.col("share").desc())),
        )
        .groupBy("grp", "route_id")
        .agg(
            quantile_disc("rank_b", 0.025).cast("long").alias("rank_low"),
            quantile_disc("rank_b", 0.975).cast("long").alias("rank_high"),
        )
    )
    share = F.col("on_time") / F.col("events")
    rank = F.rank().over(Window.partitionBy("grp", "sufficient").orderBy(share.desc()))
    return (
        point.withColumn("sufficient", sufficient)
        .join(ci, ["grp", "route_id"], "left")
        .join(ranked, ["grp", "route_id"], "left")
        .select(
            "grp",
            "route_id",
            "events",
            "trips",
            "on_time",
            F.round(share, 4).alias("on_time_share"),
            F.round("lo", 4).alias("ci_low"),
            F.round("hi", 4).alias("ci_high"),
            "sufficient",
            F.when(F.col("sufficient"), rank).cast("long").alias("rank"),
            "rank_low",
            "rank_high",
        )
    )


def route_hour_scorecard(events: DataFrame, weights: DataFrame) -> DataFrame:
    keys = ["grp", "route_id", "service_hour"]
    per_trip = events.groupBy(*keys, "service_date", "static_trip_id").agg(
        F.count("*").alias("n"), F.sum("on_time").cast("long").alias("k")
    )
    ci = (
        _resampled(per_trip, weights, keys)
        .groupBy(*keys)
        .agg(
            F.percentile("share", F.lit(0.025)).alias("lo"),
            F.percentile("share", F.lit(0.975)).alias("hi"),
        )
    )
    point = per_trip.groupBy(*keys).agg(
        F.sum("n").cast("long").alias("events"),
        F.count("*").alias("trips"),
        F.sum("k").alias("k"),
    )
    return point.join(ci, keys, "left").select(
        *keys,
        "events",
        "trips",
        F.round(F.col("k") / F.col("events"), 4).alias("on_time_share"),
        F.round("lo", 4).alias("ci_low"),
        F.round("hi", 4).alias("ci_high"),
        ((F.col("events") >= MIN_EVENTS) & (F.col("trips") >= MIN_TRIPS)).alias("sufficient"),
    )


def stop_hour_reliability(events: DataFrame) -> DataFrame:
    """BR8: what a rider at this stop can expect from this route in this hour."""
    k, n = F.sum("on_time"), F.count("*")
    return events.groupBy("grp", "route_id", "direction_id", "stop_id", "service_hour").agg(
        n.alias("events"),
        k.cast("long").alias("on_time"),
        F.round(F.avg("on_time"), 4).alias("on_time_share"),
        F.round(wilson(k, n, -1), 4).alias("ci_low"),
        F.round(wilson(k, n, 1), 4).alias("ci_high"),
        F.sum((F.col("delay_s") > LATE_S).cast("long")).alias("late"),
        F.sum((F.col("delay_s") < -EARLY_S).cast("long")).alias("early"),
        quantile_disc("delay_s", 0.5).alias("p50_delay_s"),
        quantile_disc("delay_s", 0.9).alias("p90_delay_s"),
        (n >= MIN_EVENTS).alias("sufficient"),
    )
