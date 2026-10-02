"""Gold KPI tables from Silver stop events: BR1 on-time performance and BR2 headway regularity.

Batch job over the Silver tables written by silver_events. Definitions follow golden/sql/04 and
05 (implemented here with the Spark DataFrame API, independently of that SQL):

  BR1  otp_summary, otp_route_hour, delay_sanity_summary
       on time = at most EARLY_S early and at most LATE_S late (MTA band: -1 / +5 min)
  BR2  headways, headway_regularity, headway_summary
       observed headway = gap between consecutive passages of different vehicles on one route at
       one stop; classified against the median scheduled headway at that stop in that hour

Usage: spark-submit gold_kpis.py [--prefix rt]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from pyspark.sql import Column, DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from transitometer.pipeline.layout import lakehouse_root

EARLY_S = 60
LATE_S = 300
BUNCHED_RATIO = 0.25  # headway at most this share of the reference
GAP_RATIO = 2.0  # headway at least this multiple of the reference
REGULAR_TOLERANCE = 0.2  # |headway / reference - 1| within this


def otp_class(delay: Column) -> Column:
    return F.when(delay < -EARLY_S, "early").when(delay > LATE_S, "late").otherwise("on_time")


def share(condition: Column) -> Column:
    return F.round(F.avg(condition.cast("int")), 4)


def otp_tables(events: DataFrame) -> dict[str, DataFrame]:
    klass = otp_class(F.col("delay_s"))
    scoped = events.select("grp", "service_date", F.lit("all_stops").alias("scope"), "delay_s")
    scoped = scoped.unionByName(
        events.where("timepoint").select(
            "grp", "service_date", F.lit("timepoints").alias("scope"), "delay_s"
        )
    )
    return {
        "otp_summary": scoped.groupBy("grp", "service_date", "scope").agg(
            F.count("*").alias("events"),
            share(klass == "on_time").alias("on_time_share"),
            share(klass == "early").alias("early_share"),
            share(klass == "late").alias("late_share"),
            F.median("delay_s").cast("double").alias("median_delay_s"),
        ),
        "otp_route_hour": events.groupBy("grp", "service_date", "route_id", "service_hour").agg(
            F.count("*").alias("events"),
            share(klass == "on_time").alias("on_time_share"),
            share(klass == "late").alias("late_share"),
            F.median("delay_s").cast("double").alias("median_delay_s"),
        ),
        "delay_sanity_summary": events.groupBy("grp", "service_date").agg(
            F.count("*").alias("events"),
            F.sum((F.abs("delay_s") > 6 * 3600).cast("long")).alias("events_over_6h"),
        ),
    }


def hour_of(seconds: Column) -> Column:
    return F.floor((seconds - F.col("base")) / 3600).cast("long")


def scheduled_headway_ref(stops: DataFrame) -> DataFrame:
    """Median scheduled gap per route, stop and hour, over intermediate once-visited stops."""
    trip = ["grp", "service_date", "trip_id"]
    bounds = stops.groupBy(*trip).agg(
        F.min("stop_sequence").alias("first_seq"), F.max("stop_sequence").alias("last_seq")
    )
    visits = Window.partitionBy("grp", "service_date", "trip_id", "stop_id")
    intermediate = (
        stops.join(bounds, trip)
        .where(~F.col("stop_sequence").isin(F.col("first_seq"), F.col("last_seq")))
        .withColumn("visits", F.count("*").over(visits))
        .where(F.col("visits") == 1)
    )
    order = Window.partitionBy("grp", "service_date", "route_id", "stop_id").orderBy(
        "sched_arrival", "trip_id"
    )
    gaps = intermediate.select(
        "grp",
        "service_date",
        "route_id",
        "stop_id",
        hour_of(F.col("sched_arrival")).alias("service_hour"),
        (F.col("sched_arrival") - F.lag("sched_arrival").over(order)).alias("gap"),
    )
    return (
        gaps.where(F.col("gap") > 0)
        .groupBy("grp", "service_date", "route_id", "stop_id", "service_hour")
        .agg(F.median("gap").cast("double").alias("ref_headway_s"))
    )


def passages(trip_stops: DataFrame, observed: DataFrame, matched: DataFrame) -> DataFrame:
    """Every observed passage a rider sees: KPI events, ambiguous ones and added service."""
    kpi = trip_stops.select(
        "grp",
        "service_date",
        "route_id",
        "stop_id",
        F.col("static_trip_id").alias("trip_key"),
        "trip_id",
        "unit",
        "observed_arrival",
        F.when(F.col("observations") > 1, "ambiguous").otherwise("scheduled").alias("source"),
    )
    first = Window.partitionBy("grp", "service_date", "trip_id", "stop_id").orderBy(
        "last_prediction", "unit"
    )
    unscheduled = (
        observed.join(matched, ["grp", "trip_id", "service_date"], "left_anti")
        .where((F.col("status") == "passed") & F.col("rt_route_id").isNotNull())
        .withColumn("rank", F.row_number().over(first))
        .where(F.col("rank") == 1)
        .select(
            "grp",
            "service_date",
            F.col("rt_route_id").alias("route_id"),
            "stop_id",
            F.concat(F.lit("rt:"), "trip_id").alias("trip_key"),
            "trip_id",
            "unit",
            F.col("last_prediction").alias("observed_arrival"),
            F.lit("unscheduled").alias("source"),
        )
    )
    return kpi.unionByName(unscheduled)


def headway_tables(
    trip_stops: DataFrame, observed: DataFrame, matched: DataFrame, stops: DataFrame
) -> dict[str, DataFrame]:
    bases = stops.select("service_date", "base").distinct()
    w = Window.partitionBy("grp", "service_date", "route_id", "stop_id").orderBy(
        "observed_arrival", "trip_key"
    )
    ordered = (
        passages(trip_stops, observed, matched)
        .join(bases, "service_date")
        .select(
            "grp",
            "service_date",
            "route_id",
            "stop_id",
            hour_of(F.col("observed_arrival")).alias("service_hour"),
            "trip_key",
            "trip_id",
            "unit",
            "source",
            "observed_arrival",
            F.lag("trip_key").over(w).alias("prev_trip_key"),
            F.lag("unit").over(w).alias("prev_unit"),
            F.lag("source").over(w).alias("prev_source"),
            (F.col("observed_arrival") - F.lag("observed_arrival").over(w)).alias("headway_s"),
        )
    )
    h, r = F.col("headway_s"), F.col("ref_headway_s")
    headways = (
        ordered.join(
            scheduled_headway_ref(stops),
            ["grp", "service_date", "route_id", "stop_id", "service_hour"],
        )
        .where(h.isNotNull() & (r > 0) & (F.col("unit") != F.col("prev_unit")))
        .withColumn(
            "headway_class",
            F.when(h <= BUNCHED_RATIO * r, "bunched")
            .when(h >= GAP_RATIO * r, "gap")
            .when(F.abs(h / r - 1) <= REGULAR_TOLERANCE, "regular")
            .otherwise("irregular"),
        )
        .drop("prev_unit")
    )
    klass = F.col("headway_class")
    return {
        "headways": headways,
        "headway_regularity": headways.groupBy(
            "grp", "service_date", "route_id", "service_hour"
        ).agg(
            F.count("*").alias("headways"),
            share(klass == "regular").alias("regular_share"),
            F.sum((klass == "bunched").cast("long")).alias("bunched"),
            F.sum((klass == "gap").cast("long")).alias("gaps"),
        ),
        "headway_summary": headways.groupBy("grp", "service_date").agg(
            F.count("*").alias("headways"),
            share(klass == "regular").alias("regular_share"),
            share(klass == "bunched").alias("bunched_share"),
            share(klass == "gap").alias("gap_share"),
            share((F.col("source") != "scheduled") | (F.col("prev_source") != "scheduled")).alias(
                "non_kpi_passage_share"
            ),
        ),
    }


def build_session() -> SparkSession:
    return (
        SparkSession.builder.appName("transitometer-gold-kpis")
        .master(os.environ.get("SPARK_MASTER", "local[8]"))
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config(
            "spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog"
        )
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.parquet.compression.codec", "zstd")
        .getOrCreate()
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", default="rt")
    parser.add_argument("--lakehouse", default=os.environ.get("LAKEHOUSE_DIR", "/data/lakehouse"))
    args = parser.parse_args(argv)
    root = lakehouse_root(args.lakehouse, args.prefix)
    spark = build_session()
    spark.sparkContext.setLogLevel("WARN")

    def silver(name: str) -> DataFrame:
        return spark.read.format("delta").load(f"{root}/silver/{name}")

    tables = {
        **otp_tables(silver("stop_events")),
        **headway_tables(
            silver("trip_stop_events"),
            silver("observed_events"),
            silver("matched_trips"),
            silver("scheduled_stops"),
        ),
    }
    counts = {}
    for name, frame in tables.items():
        print(f"progress gold {name}", file=sys.stderr, flush=True)
        path = f"{root}/gold/{name}"
        frame.write.format("delta").mode("overwrite").option("overwriteSchema", "true").save(path)
        counts[name] = spark.read.format("delta").load(path).count()
    spark.stop()
    print(json.dumps({"prefix": args.prefix, "rows": counts}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
