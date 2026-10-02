"""Gold BR6: rule-based early warning, judged once per trip and vehicle at a decision point.

Definitions follow golden/sql/11_early_warning.sql (see its header for the rationale and the
pre-declared acceptance), implemented here with the Spark DataFrame API, independently of that
SQL.

Decision point: the first KPI event at or past the middle of the trip's scheduled stops that is
followed by at least one more KPI event of the same vehicle (the outcome is observed later and
never feeds the warning). From stops at or before it:
  trend      (delay - delay at the vehicle's first observed stop) / scheduled time between
  projected  delay + TREND_WEIGHT * trend * scheduled time still to go to the last stop
Warnings and naive baselines:
  late     rule: projected > LATE_S              baseline: delay > LATE_S
  bunched  rule: headway <= HEADWAY_RATIO x ref  baseline: already bunched at the decision stop
Outcomes: late = delay at the vehicle's last observed KPI stop > LATE_S; bunched = classified
bunched at any later KPI stop.
"""

from __future__ import annotations

from pyspark.sql import Column, DataFrame, Window
from pyspark.sql import functions as F

from transitometer.pipeline.gold_segments import sched_positions

LATE_S = 300
TREND_WEIGHT = 0.5  # fixed on the development day (first golden day); the other day is held out
HEADWAY_RATIO = 0.5


def warning_decisions(stop_events: DataFrame, stops: DataFrame, headways: DataFrame) -> DataFrame:
    trip = ["grp", "service_date", "static_trip_id"]
    positions = sched_positions(stops)
    trip_len = positions.groupBy(*trip).agg(F.max("pos").alias("n_stops"))
    trip_end = (
        stops.withColumnRenamed("trip_id", "static_trip_id")
        .groupBy(*trip)
        .agg(F.max("sched_arrival").alias("last_sched"))
    )
    heads = headways.select(
        "grp",
        "service_date",
        "route_id",
        "stop_id",
        F.col("trip_key").alias("static_trip_id"),
        "headway_s",
        "ref_headway_s",
        "headway_class",
    )
    events = (
        stop_events.join(positions, [*trip, "stop_sequence"])
        .join(trip_len, trip)
        .join(trip_end, trip)
        .join(heads, ["grp", "service_date", "route_id", "stop_id", "static_trip_id"], "left")
    )
    unit = Window.partitionBy(*trip, "unit")
    ordered = unit.orderBy("stop_sequence")
    later = ordered.rowsBetween(1, Window.unboundedFollowing)
    inputs = events.select(
        "*",
        F.first("delay_s").over(ordered).alias("first_delay"),
        F.first("sched_arrival").over(ordered).alias("first_sched"),
        F.max_by("delay_s", "stop_sequence").over(unit).alias("final_delay"),
        F.max("stop_sequence").over(unit).alias("last_observed_seq"),
        F.sum((F.col("headway_class") == "bunched").cast("int")).over(later).alias("later_bunched"),
    )
    decisions = (
        inputs.where(
            (2 * F.col("pos") >= F.col("n_stops"))
            & (F.col("stop_sequence") < F.col("last_observed_seq"))
        )
        .withColumn("rank", F.row_number().over(ordered))
        .where(F.col("rank") == 1)
    )
    trend = F.when(
        F.col("sched_arrival") > F.col("first_sched"),
        (F.col("delay_s") - F.col("first_delay")) / (F.col("sched_arrival") - F.col("first_sched")),
    ).otherwise(F.lit(0.0))
    with_trend = decisions.withColumn("trend_raw", trend)
    # Same operation order as the reference: delay + ((weight * trend) * time to go).
    projected = F.col("delay_s") + (F.lit(TREND_WEIGHT) * F.col("trend_raw")) * (
        F.col("last_sched") - F.col("sched_arrival")
    )
    return with_trend.select(
        *trip,
        "unit",
        "route_id",
        F.col("stop_id").alias("decision_stop"),
        F.col("observed_arrival").alias("decision_time"),
        "delay_s",
        F.round("trend_raw", 6).alias("trend"),
        F.round(projected).alias("projected_delay_s"),
        "headway_s",
        "ref_headway_s",
        (projected > LATE_S).alias("warn_late"),
        (F.col("delay_s") > LATE_S).alias("baseline_late"),
        (F.col("final_delay") > LATE_S).alias("late"),
        F.coalesce(
            F.col("headway_s") <= HEADWAY_RATIO * F.col("ref_headway_s"), F.lit(False)
        ).alias("warn_bunched"),
        F.coalesce(F.col("headway_class") == "bunched", F.lit(False)).alias("baseline_bunched"),
        (F.coalesce(F.col("later_bunched"), F.lit(0)) > 0).alias("bunched"),
    )


def _share(numerator: Column, denominator: Column) -> Column:
    return F.round(numerator / F.when(denominator != 0, denominator), 4)


def early_warning_summary(decisions: DataFrame) -> DataFrame:
    """Precision, recall and F1 of each rule against its naive baseline, per mode and day."""
    pairs = [
        ("late", "rule", "warn_late", "late"),
        ("late", "baseline", "baseline_late", "late"),
        ("bunched", "rule", "warn_bunched", "bunched"),
        ("bunched", "baseline", "baseline_bunched", "bunched"),
    ]
    scored = None
    for outcome, method, warned, actual in pairs:
        part = decisions.select(
            "grp",
            "service_date",
            F.lit(outcome).alias("outcome"),
            F.lit(method).alias("method"),
            F.col(warned).alias("warned"),
            F.col(actual).alias("actual"),
        )
        scored = part if scored is None else scored.unionByName(part)
    assert scored is not None
    w, a = F.col("warned"), F.col("actual")
    counts = scored.groupBy("grp", "service_date", "outcome", "method").agg(
        F.count("*").alias("decisions"),
        F.sum(a.cast("long")).alias("positives"),
        F.sum((w & a).cast("long")).alias("tp"),
        F.sum((w & ~a).cast("long")).alias("fp"),
        F.sum((~w & a).cast("long")).alias("fn"),
    )
    tp, fp, fn = F.col("tp"), F.col("fp"), F.col("fn")
    return counts.select(
        "*",
        _share(tp, tp + fp).alias("precision"),
        _share(tp, tp + fn).alias("recall"),
        _share(2 * tp, 2 * tp + fp + fn).alias("f1"),
    )
