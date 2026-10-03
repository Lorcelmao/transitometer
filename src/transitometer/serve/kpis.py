"""KPI queries behind the app pages, in DuckDB SQL over one of three interchangeable sources.

  golden    the frozen reference tables in golden/tables/*.parquet (host development, no Docker)
  gold      the Spark Gold Delta tables in <lakehouse>/gold/<table> (the real pipeline output)
  snapshot  a validated copy of the Spark Gold tables in showcase/data/*.parquet, committed to
            the repository so the public apps run without Docker, Delta or the lakehouse

All sources use the same table names and columns, so each page query is written once and the
app can show the pipeline output and the reference side by side.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from transitometer.pipeline.layout import lakehouse_root

REPO = Path(__file__).resolve().parents[3]
MIN_EVENTS = 30  # route rankings ignore route-hours with fewer observed events
MIN_TRIPS = 10  # delivery rankings ignore routes with fewer observable scheduled trips
SNAPSHOT_DIR = REPO / "showcase" / "data"

# Every table the queries below read: the snapshot copies exactly these (a test keeps the list
# equal to the queries). stop_names is optional display data; the queries work without it.
APP_TABLES = (
    "otp_summary",
    "otp_route_hour",
    "headway_summary",
    "headway_regularity",
    "missing_trip_summary",
    "missing_by_route",
    "feed_quality_score",
    "feed_quality_metrics",
    "route_scorecard",
    "stop_hour_reliability",
    "delay_attribution_summary",
    "segment_travel_stats",
    "early_warning_summary",
    "stop_names",
    "stop_locations",
)


@dataclass(frozen=True)
class Source:
    kind: str  # "golden", "gold" or "snapshot"
    root: str  # Parquet folder (golden, snapshot), or the lakehouse root holding gold/

    @property
    def parquet(self) -> bool:
        return self.kind in ("golden", "snapshot")

    def table(self, name: str) -> str:
        """FROM-clause expression for one KPI table."""
        if self.parquet:
            return _quoted(f"{self.root}/{name}.parquet")
        return f"delta_scan({_quoted(f'{self.root}/gold/{name}')})"

    def has(self, name: str) -> bool:
        """Whether a table exists in this source (optional tables, e.g. stop display names)."""
        if self.parquet:
            return Path(self.root, f"{name}.parquet").exists()
        return Path(self.root, "gold", name, "_delta_log").exists()


def _quoted(path: str) -> str:
    return "'" + path.replace("\\", "/").replace("'", "''") + "'"


def source_from_env() -> Source:
    kind = os.environ.get("TRANSITOMETER_APP_SOURCE", "golden")
    if kind == "golden":
        tables = os.environ.get("GOLDEN_TABLES_DIR", str(REPO / "golden" / "tables"))
        return Source("golden", tables)
    if kind == "gold":
        base = os.environ.get("LAKEHOUSE_DIR", "/data/lakehouse")
        return Source("gold", lakehouse_root(base, os.environ.get("TRANSITOMETER_PREFIX", "rt")))
    if kind == "snapshot":
        return Source("snapshot", os.environ.get("TRANSITOMETER_SNAPSHOT_DIR", str(SNAPSHOT_DIR)))
    raise ValueError(
        f"TRANSITOMETER_APP_SOURCE must be 'golden', 'gold' or 'snapshot', not {kind!r}"
    )


def connect(source: Source) -> duckdb.DuckDBPyConnection:
    if source.kind == "gold":
        from transitometer.serve import lakehouse  # loads the Delta extension

        return lakehouse.connect()
    return duckdb.connect()


def _rows(
    con: duckdb.DuckDBPyConnection, sql: str, params: list[Any] | None = None
) -> list[dict[str, Any]]:
    cursor = con.execute(sql, params or [])
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def service_dates(con: duckdb.DuckDBPyConnection, src: Source) -> list[str]:
    sql = f"SELECT DISTINCT service_date FROM {src.table('otp_summary')} ORDER BY 1"
    return [row["service_date"] for row in _rows(con, sql)]


def otp_overview(con: duckdb.DuckDBPyConnection, src: Source) -> list[dict[str, Any]]:
    """BR1 headline: on-time / early / late shares per mode, day and scope."""
    return _rows(con, f"SELECT * FROM {src.table('otp_summary')} ORDER BY grp, service_date, scope")


def otp_route_hour(
    con: duckdb.DuckDBPyConnection, src: Source, grp: str, service_date: str
) -> list[dict[str, Any]]:
    """BR1 detail: on-time share per route and service hour (heatmap)."""
    sql = (
        f"SELECT route_id, service_hour, events, on_time_share, late_share, median_delay_s"
        f" FROM {src.table('otp_route_hour')} WHERE grp = ? AND service_date = ?"
        f" ORDER BY route_id, service_hour"
    )
    return _rows(con, sql, [grp, service_date])


def least_punctual_routes(
    con: duckdb.DuckDBPyConnection, src: Source, grp: str, service_date: str, limit: int = 15
) -> list[dict[str, Any]]:
    """BR1 ranking: routes by event-weighted on-time share, ignoring thinly observed hours."""
    sql = (
        f"SELECT route_id, sum(events) AS events,"
        f" round(sum(on_time_share * events) / sum(events), 4) AS on_time_share,"
        f" round(sum(late_share * events) / sum(events), 4) AS late_share"
        f" FROM {src.table('otp_route_hour')}"
        f" WHERE grp = ? AND service_date = ? AND events >= ?"
        f" GROUP BY route_id ORDER BY on_time_share, route_id LIMIT ?"
    )
    return _rows(con, sql, [grp, service_date, MIN_EVENTS, limit])


def headway_overview(con: duckdb.DuckDBPyConnection, src: Source) -> list[dict[str, Any]]:
    """BR2 headline: regular / bunched / gap shares per mode and day."""
    sql = f"SELECT * FROM {src.table('headway_summary')} ORDER BY grp, service_date"
    return _rows(con, sql)


def most_bunched_routes(
    con: duckdb.DuckDBPyConnection, src: Source, grp: str, service_date: str, limit: int = 15
) -> list[dict[str, Any]]:
    """BR2 ranking: routes by share of bunched headways (at most 25 % of the scheduled one)."""
    sql = (
        f"SELECT route_id, sum(headways) AS headways, sum(bunched) AS bunched, sum(gaps) AS gaps,"
        f" round(sum(bunched) / sum(headways), 4) AS bunched_share,"
        f" round(sum(regular_share * headways) / sum(headways), 4) AS regular_share"
        f" FROM {src.table('headway_regularity')}"
        f" WHERE grp = ? AND service_date = ?"
        f" GROUP BY route_id HAVING sum(headways) >= ?"
        f" ORDER BY bunched_share DESC, route_id LIMIT ?"
    )
    return _rows(con, sql, [grp, service_date, MIN_EVENTS, limit])


def headway_route_hour(
    con: duckdb.DuckDBPyConnection, src: Source, grp: str, service_date: str
) -> list[dict[str, Any]]:
    sql = (
        f"SELECT route_id, service_hour, headways, regular_share, bunched, gaps"
        f" FROM {src.table('headway_regularity')} WHERE grp = ? AND service_date = ?"
        f" ORDER BY route_id, service_hour"
    )
    return _rows(con, sql, [grp, service_date])


def delivery_overview(con: duckdb.DuckDBPyConnection, src: Source) -> list[dict[str, Any]]:
    """BR3 headline: scheduled trips per delivery class, per mode and day."""
    sql = f"SELECT * FROM {src.table('missing_trip_summary')} ORDER BY grp, service_date"
    return _rows(con, sql)


def least_delivered_routes(
    con: duckdb.DuckDBPyConnection, src: Source, grp: str, service_date: str, limit: int = 15
) -> list[dict[str, Any]]:
    """BR3 ranking: routes by share of observable scheduled trips not delivered."""
    sql = (
        f"SELECT route_id, scheduled, delivered, partial, missing, not_run, unknown,"
        f" not_delivered_share"
        f" FROM {src.table('missing_by_route')}"
        f" WHERE grp = ? AND service_date = ? AND scheduled - unknown >= ?"
        f" ORDER BY not_delivered_share DESC, route_id LIMIT ?"
    )
    return _rows(con, sql, [grp, service_date, MIN_TRIPS, limit])


def feed_scores(con: duckdb.DuckDBPyConnection, src: Source) -> list[dict[str, Any]]:
    """BR7 headline: conformance score per feed and day, with the failed checks."""
    return _rows(con, f"SELECT * FROM {src.table('feed_quality_score')} ORDER BY feed, day")


def route_scorecards(con: duckdb.DuckDBPyConnection, src: Source, grp: str) -> list[dict[str, Any]]:
    """BR5: every route's pooled on-time share with its 95 % bootstrap interval and rank interval.

    Sufficiently observed routes first, by rank; the others follow without a rank.
    """
    sql = (
        f"SELECT route_id, events, trips, on_time_share, ci_low, ci_high, sufficient, rank,"
        f" rank_low, rank_high FROM {src.table('route_scorecard')} WHERE grp = ?"
        f" ORDER BY sufficient DESC, rank NULLS LAST, route_id"
    )
    return _rows(con, sql, [grp])


def stop_routes(con: duckdb.DuckDBPyConnection, src: Source, grp: str) -> list[str]:
    """BR8: routes with at least one stop-hour observed often enough to be scored."""
    sql = (
        f"SELECT DISTINCT route_id FROM {src.table('stop_hour_reliability')}"
        f" WHERE grp = ? AND sufficient ORDER BY route_id"
    )
    return [row["route_id"] for row in _rows(con, sql, [grp])]


def route_stops(
    con: duckdb.DuckDBPyConnection, src: Source, grp: str, route_id: str
) -> list[dict[str, Any]]:
    """BR8: the stops of a route with their observed arrivals, named when names are available."""
    name = "n.stop_name" if src.has("stop_names") else "NULL"
    join = (
        f" LEFT JOIN {src.table('stop_names')} n ON n.grp = r.grp AND n.stop_id = r.stop_id"
        if src.has("stop_names")
        else ""
    )
    sql = (
        f"SELECT r.direction_id, r.stop_id, any_value({name}) AS stop_name,"
        f" sum(r.events) AS events, count(*) FILTER (WHERE r.sufficient) AS scored_hours"
        f" FROM {src.table('stop_hour_reliability')} r{join}"
        f" WHERE r.grp = ? AND r.route_id = ?"
        f" GROUP BY ALL HAVING scored_hours > 0"
        f" ORDER BY r.direction_id NULLS LAST, stop_name NULLS LAST, r.stop_id"
    )
    return _rows(con, sql, [grp, route_id])


STOP_HOUR_COLUMNS = (
    "service_hour, events, on_time, on_time_share, ci_low, ci_high, late, early,"
    " p50_delay_s, p90_delay_s, sufficient"
)


def stop_hours(
    con: duckdb.DuckDBPyConnection,
    src: Source,
    grp: str,
    route_id: str,
    direction_id: int | None,
    stop_id: str,
) -> list[dict[str, Any]]:
    """BR8: hour by hour at one stop: on-time share, Wilson interval and typical delays."""
    sql = (
        f"SELECT {STOP_HOUR_COLUMNS} FROM {src.table('stop_hour_reliability')}"
        f" WHERE grp = ? AND route_id = ? AND direction_id IS NOT DISTINCT FROM ? AND stop_id = ?"
        f" ORDER BY service_hour"
    )
    return _rows(con, sql, [grp, route_id, direction_id, stop_id])


def route_stop_hours(
    con: duckdb.DuckDBPyConnection, src: Source, grp: str, route_id: str
) -> list[dict[str, Any]]:
    """BR8: stop_hours for every stop of a route in one query (the static export's route files)."""
    sql = (
        f"SELECT direction_id, stop_id, {STOP_HOUR_COLUMNS}"
        f" FROM {src.table('stop_hour_reliability')} WHERE grp = ? AND route_id = ?"
        f" ORDER BY direction_id NULLS LAST, stop_id, service_hour"
    )
    return _rows(con, sql, [grp, route_id])


def stop_map(con: duckdb.DuckDBPyConnection, src: Source, grp: str) -> list[dict[str, Any]]:
    """BR8 map: every located stop with its arrivals and on-time arrivals pooled over all routes
    and hours, the route (and direction) that serves it most, and its display name."""
    name = "n.stop_name" if src.has("stop_names") else "NULL"
    names = (
        f" LEFT JOIN {src.table('stop_names')} n ON n.grp = l.grp AND n.stop_id = l.stop_id"
        if src.has("stop_names")
        else ""
    )
    sql = (
        f"WITH per_route AS ("
        f" SELECT stop_id, route_id, direction_id, sum(events) AS events, sum(on_time) AS on_time"
        f" FROM {src.table('stop_hour_reliability')} WHERE grp = ? GROUP BY ALL),"
        f" ranked AS (SELECT *, row_number() OVER (PARTITION BY stop_id"
        f" ORDER BY events DESC, route_id, direction_id NULLS LAST) AS pick FROM per_route),"
        f" per_stop AS (SELECT stop_id, sum(events)::BIGINT AS events,"
        f" sum(on_time)::BIGINT AS on_time FROM per_route GROUP BY stop_id)"
        f" SELECT s.stop_id, {name} AS stop_name, l.lat, l.lon, s.events, s.on_time,"
        f" s.on_time / s.events AS on_time_share, r.route_id, r.direction_id"
        f" FROM per_stop s JOIN ranked r ON r.stop_id = s.stop_id AND r.pick = 1"
        f" JOIN {src.table('stop_locations')} l ON l.grp = ? AND l.stop_id = s.stop_id{names}"
        f" ORDER BY s.stop_id"
    )
    return _rows(con, sql, [grp, grp])


def delay_overview(con: duckdb.DuckDBPyConnection, src: Source) -> list[dict[str, Any]]:
    """BR4 headline: mean delay inherited at the first observed stop, gained en route, and final."""
    sql = f"SELECT * FROM {src.table('delay_attribution_summary')} ORDER BY grp, service_date"
    return _rows(con, sql)


def costly_segments(
    con: duckdb.DuckDBPyConnection, src: Source, grp: str, min_segments: int, limit: int = 15
) -> list[dict[str, Any]]:
    """BR4: stop-to-stop segments (one route, direction and hour) that lose the most time.

    Ranked by median excess travel time over the timetable; stop names when available.
    """
    names = src.has("stop_names")
    label = (
        "coalesce(f.stop_name, s.from_stop) AS from_name,"
        " coalesce(t.stop_name, s.to_stop) AS to_name"
        if names
        else "s.from_stop AS from_name, s.to_stop AS to_name"
    )
    joins = (
        f" LEFT JOIN {src.table('stop_names')} f ON f.grp = s.grp AND f.stop_id = s.from_stop"
        f" LEFT JOIN {src.table('stop_names')} t ON t.grp = s.grp AND t.stop_id = s.to_stop"
        if names
        else ""
    )
    sql = (
        f"SELECT s.route_id, s.direction_id, s.service_hour, s.from_stop, s.to_stop, {label},"
        f" s.segments, s.sched_travel_s, s.p50_travel_s, s.p90_travel_s, s.median_excess_s"
        f" FROM {src.table('segment_travel_stats')} s{joins}"
        f" WHERE s.grp = ? AND s.segments >= ?"
        f" ORDER BY s.median_excess_s DESC, s.route_id, s.from_stop, s.service_hour LIMIT ?"
    )
    return _rows(con, sql, [grp, min_segments, limit])


def warning_summary(con: duckdb.DuckDBPyConnection, src: Source) -> list[dict[str, Any]]:
    """BR6: precision, recall and F1 of each warning rule and its naive baseline."""
    sql = (
        f"SELECT * FROM {src.table('early_warning_summary')}"
        f" ORDER BY grp, service_date, outcome, method DESC"
    )
    return _rows(con, sql)


def feed_metric(
    con: duckdb.DuckDBPyConnection, src: Source, feed: str, day: str, metric: str
) -> float | None:
    """One feed-quality metric value (NULL when the check had no data)."""
    sql = (
        f"SELECT value FROM {src.table('feed_quality_metrics')}"
        f" WHERE feed = ? AND day = ? AND metric = ?"
    )
    rows = _rows(con, sql, [feed, day, metric])
    return rows[0]["value"] if rows else None


def feed_checks(
    con: duckdb.DuckDBPyConnection, src: Source, feed: str, day: str
) -> list[dict[str, Any]]:
    """BR7 detail: every quality check of one feed-day against its threshold."""
    sql = (
        f"SELECT metric, value, threshold, passed FROM {src.table('feed_quality_metrics')}"
        f" WHERE feed = ? AND day = ? ORDER BY passed, metric"
    )
    return _rows(con, sql, [feed, day])
