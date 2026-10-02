"""KPI queries behind the app pages, in DuckDB SQL over one of two interchangeable sources.

  golden  the frozen reference tables in golden/tables/*.parquet (host development, no Docker)
  gold    the Spark Gold Delta tables in <lakehouse>/gold/<table> (the real pipeline output)

Both sources use the same table names and columns, so each page query is written once and the
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


@dataclass(frozen=True)
class Source:
    kind: str  # "golden" or "gold"
    root: str  # golden tables folder, or the lakehouse root holding gold/

    def table(self, name: str) -> str:
        """FROM-clause expression for one KPI table."""
        if self.kind == "golden":
            return _quoted(f"{self.root}/{name}.parquet")
        return f"delta_scan({_quoted(f'{self.root}/gold/{name}')})"


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
    raise ValueError(f"TRANSITOMETER_APP_SOURCE must be 'golden' or 'gold', not {kind!r}")


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
