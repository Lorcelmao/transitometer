"""Service-day arithmetic shared by the Spark jobs (pure Python + DuckDB, testable on the host)."""

from __future__ import annotations

from datetime import datetime

import duckdb

TIMEZONE = "America/New_York"
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def day_base(service_date: str, timezone: str = TIMEZONE) -> int:
    """Epoch seconds of GTFS time zero: noon of the service day in agency time, minus 12 hours.

    The 12 hours are elapsed time, not wall-clock time, so on a DST change day time zero is 23:00
    or 01:00 local; stop times past 24:00 are then plain additions (GTFS reference, stop_times).
    DuckDB does the time-zone lookup: it carries its own tz database, which Windows Python and
    slim container images may lack.
    """
    day = datetime.strptime(service_date, "%Y%m%d")
    with duckdb.connect() as con:
        row = con.execute(
            "SELECT epoch(make_timestamptz(?, ?, ?, 12, 0, 0, ?))::BIGINT",
            [day.year, day.month, day.day, timezone],
        ).fetchone()
    assert row is not None
    return int(row[0]) - 12 * 3600


def weekday(service_date: str) -> str:
    """Calendar column name of the service day ('monday' ... 'sunday')."""
    return WEEKDAYS[datetime.strptime(service_date, "%Y%m%d").weekday()]
