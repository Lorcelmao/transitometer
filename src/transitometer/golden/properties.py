"""Invariants every result set must satisfy, whichever engine produced it.

Each check is a SQL query over the exported tables that counts violating rows; 0 means it holds.
A NULL where a value is required counts as a violation. The on-time band (-60 .. +300 s) is the
frozen golden one.
They complement the golden comparison: an engine can be checked before golden answers exist for
its window, and a golden run is checked against itself.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

CHECKS: dict[str, str] = {
    # BR3: the delivery classes partition the scheduled trips of every route and day.
    "delivery_classes_partition_schedule": """
        SELECT count(*) FROM missing_by_route
        WHERE scheduled IS DISTINCT FROM delivered + partial + missing + not_run + unknown""",
    "delivery_summary_matches_trips": """
        SELECT count(*) FROM missing_trip_summary s
        FULL JOIN (SELECT grp, service_date, count(*) AS n FROM trip_delivery GROUP BY ALL) t
          USING (grp, service_date)
        WHERE s.scheduled IS DISTINCT FROM t.n""",
    # No result row references a trip absent from the day's timetable.
    "stop_events_reference_scheduled_trips": """
        SELECT count(*) FROM stop_events e
        WHERE NOT EXISTS (SELECT 1 FROM trip_delivery t
                          WHERE t.grp = e.grp AND t.service_date = e.service_date
                            AND t.trip_id = e.static_trip_id)""",
    # KPI events are unambiguous, one per scheduled trip-stop.
    "stop_events_one_per_trip_stop": """
        SELECT count(*) FROM (SELECT grp, service_date, static_trip_id, stop_id FROM stop_events
                              GROUP BY ALL HAVING count(*) > 1)""",
    "stop_events_unambiguous": "SELECT count(*) FROM stop_events WHERE observations <> 1",
    # Timestamps stay within the service day: a trip matched to the wrong day is ~24 h off.
    "stop_events_near_timetable": """
        SELECT count(*) FROM stop_events WHERE coalesce(abs(delay_s) > 6 * 3600, true)""",
    "delay_is_observed_minus_scheduled": """
        SELECT count(*) FROM stop_events
        WHERE delay_s IS DISTINCT FROM observed_arrival - sched_arrival OR delay_s IS NULL""",
    # BR4: delay at the last observed stop = inherited + gained, for every trip and vehicle.
    "delay_attribution_sums": """
        SELECT count(*) FROM trip_delay_attribution
        WHERE final_delay_s IS DISTINCT FROM inherited_delay_s + gained_delay_s
           OR final_delay_s IS NULL""",
    "segment_excess_consistent": """
        SELECT count(*) FROM segments
        WHERE excess_s IS DISTINCT FROM observed_travel_s - sched_travel_s
           OR excess_s IS DISTINCT FROM to_delay - from_delay OR excess_s IS NULL""",
    # BR8 holds exactly the BR1 events, per stop and hour.
    "stop_hour_parity_with_events": """
        SELECT count(*) FROM stop_hour_reliability r
        FULL JOIN (SELECT grp, route_id, direction_id, stop_id, service_hour, count(*) AS n,
                          sum(CASE WHEN delay_s BETWEEN -60 AND 300 THEN 1 ELSE 0 END) AS k
                   FROM stop_events GROUP BY ALL) e
          USING (grp, route_id, direction_id, stop_id, service_hour)
        WHERE r.events IS DISTINCT FROM e.n OR r.on_time IS DISTINCT FROM e.k""",
    # BR5: a sufficient route has a bootstrap interval and a rank.
    "scorecard_sufficient_routes_complete": """
        SELECT count(*) FROM route_scorecard
        WHERE sufficient AND (ci_low IS NULL OR ci_high IS NULL OR rank IS NULL)""",
    # BR6: confusion counts add up.
    "warning_counts_add_up": """
        SELECT count(*) FROM early_warning_summary
        WHERE tp + fn <> positives OR tp + fp > decisions""",
    # BR7: a score is exactly the share of passed checks.
    "feed_score_matches_checks": """
        SELECT count(*) FROM feed_quality_score s
        JOIN (SELECT feed, day, count(*) AS n, count(*) FILTER (WHERE passed) AS p
              FROM feed_quality_metrics GROUP BY ALL) m USING (feed, day)
        WHERE s.checks <> m.n OR s.passed <> m.p""",
}


def register_tables(con: duckdb.DuckDBPyConnection, tables_dir: Path) -> list[str]:
    """One view per exported Parquet table in `tables_dir`."""
    names = []
    for path in sorted(tables_dir.glob("*.parquet")):
        con.execute(
            f"CREATE OR REPLACE VIEW {path.stem} AS SELECT * FROM read_parquet('{path.as_posix()}')"
        )
        names.append(path.stem)
    return names


def check(tables_dir: Path) -> dict[str, int | str]:
    """Violating-row count per invariant for the tables in `tables_dir`, or the error message
    when an invariant cannot be evaluated (e.g. a table is missing)."""
    with duckdb.connect() as con:
        register_tables(con, tables_dir)
        results: dict[str, int | str] = {}
        for name, sql in CHECKS.items():
            try:
                row = con.execute(sql).fetchone()
            except duckdb.Error as exc:
                results[name] = f"{type(exc).__name__}: {exc}".splitlines()[0]
                continue
            results[name] = int(row[0]) if row else 0
    return results
