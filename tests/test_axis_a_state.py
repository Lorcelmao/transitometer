"""The shared W2 state step equals the golden headway SQL, whatever the batching and disorder."""

from __future__ import annotations

import random
from typing import Any

import duckdb
import pytest

from transitometer.axis_a import headway_state as hs
from transitometer.golden.runner import Params, render

COLUMNS = (
    "grp VARCHAR, service_date VARCHAR, route_id VARCHAR, stop_id VARCHAR, service_hour BIGINT, "
    "trip_key VARCHAR, trip_id VARCHAR, unit VARCHAR, source VARCHAR, observed_arrival BIGINT, "
    "delay_s BIGINT, ref_headway_s DOUBLE"
)
FIELDS = [c.split()[0] for c in COLUMNS.split(", ")]
DELAY = 120  # watermark delay, as both engines


def passages(seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    rows = []
    for i in range(400):
        stop = rng.choice(["S1", "S2", "S3"])
        rows.append(
            {
                "grp": "bus",
                "service_date": "20260922",
                "route_id": "B6",
                "stop_id": stop,
                "service_hour": 7,
                "trip_key": f"t{i:04d}",
                "trip_id": f"t{i:04d}",
                "unit": rng.choice(["v1", "v2", "v3", "v4"]),
                "source": rng.choice(["scheduled", "ambiguous", "unscheduled"]),
                "observed_arrival": rng.randrange(0, 20_000, 30),  # many ties on purpose
                "delay_s": None,
                "ref_headway_s": rng.choice([None, 0.0, 300.0, 600.0]),
            }
        )
    return rows


def golden(rows: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    with duckdb.connect() as con:
        con.execute(f"CREATE TABLE axis_a_passages ({COLUMNS})")
        con.executemany(
            f"INSERT INTO axis_a_passages VALUES ({', '.join(['?'] * len(FIELDS))})",
            [tuple(r[f] for f in FIELDS) for r in rows],
        )
        con.execute(render("axis_a_w2.sql", vars(Params())))
        fields = ", ".join(hs.OUTPUT_FIELDS)
        return con.execute(f"SELECT {fields} FROM axis_a_w2 ORDER BY ALL").fetchall()


def streamed(rows: list[dict[str, Any]], seed: int) -> list[tuple[Any, ...]]:
    """Deliver in event-time order with bounded disorder, in random batches, like an engine."""
    rng = random.Random(seed)
    jittered = sorted(rows, key=lambda r: r["observed_arrival"] + rng.uniform(0, DELAY - 1))
    states: dict[tuple[str, ...], hs.HeadwayState] = {}
    out: list[dict[str, Any]] = []
    max_seen = -(10**9)
    i = 0
    while i < len(jittered):
        batch = jittered[i : i + rng.randint(1, 40)]
        i += len(batch)
        watermark = max_seen - DELAY  # the watermark of the previous batches
        for r in batch:
            key = (r["grp"], r["service_date"], r["route_id"], r["stop_id"])
            hs.add(states.setdefault(key, hs.HeadwayState()), [r])
        for state in states.values():
            out += hs.release(state, watermark)
        max_seen = max([max_seen, *(r["observed_arrival"] for r in batch)])
    for state in states.values():  # end of stream: the watermark passes everything
        out += hs.release(state, float("inf"))
        assert state.late == 0
    return sorted(tuple(r[f] for f in hs.OUTPUT_FIELDS) for r in out)


@pytest.mark.parametrize("seed", range(5))
def test_state_step_equals_golden_sql(seed: int) -> None:
    rows = passages(seed)
    assert streamed(rows, seed) == golden(rows)


def test_a_passage_behind_the_released_chain_is_late_and_skipped() -> None:
    state = hs.HeadwayState()
    first = {**passages(0)[0], "observed_arrival": 1000, "trip_key": "a", "unit": "v1"}
    hs.add(state, [first])
    assert hs.release(state, 2000) == []  # first passage: nothing to pair with
    hs.add(state, [{**first, "observed_arrival": 900, "trip_key": "b", "unit": "v2"}])
    assert state.late == 1 and state.buffer == []
    assert state.last is not None and state.last["trip_key"] == "a"


def test_classes_match_the_golden_thresholds() -> None:
    assert hs.classify(150, 600.0) == "bunched"
    assert hs.classify(1200, 600.0) == "gap"
    assert hs.classify(720, 600.0) == "regular"
    assert hs.classify(721, 600.0) == "irregular"
