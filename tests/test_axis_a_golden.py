"""Golden Axis A workloads (W1, W2) on a hand-made passage table."""

from __future__ import annotations

from typing import Any

import duckdb
import pytest

from transitometer.golden.runner import Params, render

COLUMNS = (
    "grp VARCHAR, service_date VARCHAR, route_id VARCHAR, stop_id VARCHAR, service_hour BIGINT, "
    "trip_key VARCHAR, trip_id VARCHAR, unit VARCHAR, source VARCHAR, observed_arrival BIGINT, "
    "delay_s BIGINT, ref_headway_s DOUBLE"
)


def passage(
    t: int, trip: str, unit: str, delay: int | None = None, ref: float | None = 600.0
) -> tuple[Any, ...]:
    return ("bus", "20260922", "B6", "S1", 7, trip, trip, unit, "scheduled", t, delay, ref)


def run(step: str, rows: list[tuple[Any, ...]]) -> list[dict[str, Any]]:
    with duckdb.connect() as con:
        con.execute(f"CREATE TABLE axis_a_passages ({COLUMNS})")
        con.executemany(f"INSERT INTO axis_a_passages VALUES ({', '.join(['?'] * 12)})", rows)
        con.execute(render(step, vars(Params())))
        table = step.removesuffix(".sql")
        cursor = con.execute(f"SELECT * FROM {table} ORDER BY ALL")
        names = [d[0] for d in cursor.description]
        return [dict(zip(names, r, strict=True)) for r in cursor.fetchall()]


@pytest.fixture(scope="module")
def w2() -> dict[str, dict[str, Any]]:
    rows = [
        passage(1000, "k1", "v1"),
        passage(1100, "k2", "v2"),
        passage(1100, "k0", "v3"),  # same second as k2: trip_key orders it first
        passage(1700, "k3", "v4"),
        passage(1700 + 600, "k4", "v4"),  # same vehicle as k3 just before it: dropped
        passage(2300 + 1200, "k5", "v6", ref=None),  # no reference: dropped, chain continues
        passage(3500 + 600, "k6", "v7"),
        passage(4100 + 900, "k7", "v8"),
    ]
    return {r["trip_key"]: r for r in run("axis_a_w2.sql", rows)}


def test_w2_orders_ties_by_trip_key(w2: dict[str, dict[str, Any]]) -> None:
    assert w2["k0"]["prev_trip_key"] == "k1" and w2["k0"]["headway_s"] == 100
    assert w2["k2"]["prev_trip_key"] == "k0" and w2["k2"]["headway_s"] == 0


def test_w2_drops_same_vehicle_and_missing_reference_but_keeps_the_chain(
    w2: dict[str, dict[str, Any]],
) -> None:
    assert "k1" not in w2  # first passage: no previous one
    assert "k4" not in w2  # same vehicle as the passage before it
    assert "k5" not in w2  # no scheduled reference
    assert w2["k3"]["prev_trip_key"] == "k2"
    assert w2["k6"]["prev_trip_key"] == "k5"  # the dropped passage still precedes k6


def test_w2_classifies_against_the_reference(w2: dict[str, dict[str, Any]]) -> None:
    assert w2["k0"]["headway_class"] == "bunched"  # 100 <= 0.25 * 600
    assert w2["k3"]["headway_class"] == "regular"  # 600, within 20 %
    assert w2["k6"]["headway_class"] == "regular"
    assert w2["k7"]["headway_class"] == "irregular"  # 900 = 1.5 x the reference


def test_w2_gap() -> None:
    rows = run("axis_a_w2.sql", [passage(0, "a", "v1"), passage(1200, "b", "v2")])
    assert rows[0]["headway_class"] == "gap"  # 1200 >= 2 * 600


def test_w1_windows_are_tumbling_minutes_of_non_null_delays() -> None:
    rows = run(
        "axis_a_w1.sql",
        [
            passage(1000, "a", "v1", delay=60),
            passage(1019, "b", "v2", delay=120),  # 1019 < 1020: same window as 1000
            passage(1020, "c", "v3", delay=-30),  # next window
            passage(1021, "d", "v4", delay=None),  # unscheduled: no delay
            passage(2000, "e", "v5", delay=None),  # a window with no delay at all
        ],
    )
    by_start = {r["window_start"]: r for r in rows}
    assert sorted(by_start) == [960, 1020]
    first = by_start[960]
    assert (first["delays"], first["delay_sum_s"], first["min_delay_s"], first["max_delay_s"]) == (
        2,
        180,
        60,
        120,
    )
    assert first["mean_delay_s"] == pytest.approx(90.0)
    assert first["stddev_delay_s"] == pytest.approx(30.0)
    assert by_start[1020]["delays"] == 1 and by_start[1020]["stddev_delay_s"] == 0.0
