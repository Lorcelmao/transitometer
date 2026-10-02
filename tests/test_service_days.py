"""GTFS time zero in the Spark jobs must equal the golden SQL's day_base, DST days included."""

from __future__ import annotations

from datetime import datetime, timezone

import duckdb
import pytest

from transitometer.pipeline.service_days import TIMEZONE, day_base, weekday

GOLDEN_DAY_BASE = (
    "epoch(make_timestamptz(CAST(left(d, 4) AS INT), CAST(substr(d, 5, 2) AS INT),"
    f" CAST(right(d, 2) AS INT), 12, 0, 0, '{TIMEZONE}') - INTERVAL 12 HOUR)::BIGINT"
)


@pytest.mark.parametrize(
    "service_date",
    ["20260922", "20260923", "20260308", "20261101", "20260101"],  # golden days, both DST changes
)
def test_day_base_matches_the_golden_sql(service_date: str) -> None:
    with duckdb.connect() as con:
        expected = con.execute(f"SELECT {GOLDEN_DAY_BASE} FROM (SELECT ? AS d)", [service_date])
        assert day_base(service_date) == expected.fetchone()[0]  # type: ignore[index]


def test_time_zero_is_noon_minus_elapsed_hours_on_dst_days() -> None:
    # 8 Mar 2026 springs forward: noon is EDT (16:00 UTC), so time zero is 04:00 UTC, i.e.
    # 23:00 EST on 7 Mar; the day before it is 05:00 UTC, so that service day is 23 h long.
    spring = datetime(2026, 3, 8, 4, tzinfo=timezone.utc).timestamp()
    assert day_base("20260308") == int(spring)
    assert day_base("20260308") - day_base("20260307") == 23 * 3600


def test_weekday_names_follow_the_calendar_columns() -> None:
    assert weekday("20260922") == "tuesday"
    assert weekday("20260927") == "sunday"
