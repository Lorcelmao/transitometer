"""Golden BR3 (missing trips), BR4 (segments), BR5 (scorecards), BR8 (stop reliability), bus
terminal arrivals and rule edge values, on a second hand-built day where every expected value is
worked out by hand.

Bus route Q: Q0 origin, Q1..Q3 intermediate, Q4 last stop. Route H: H0 origin, H1, H2 last stop.
A heartbeat trip XQ (route Z, unscheduled) keeps the feed alive 07:00-12:00 with one outage,
09:56 -> 10:08 (720 s).
"""

from __future__ import annotations

import dataclasses
import hashlib
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import duckdb
import pyarrow.parquet as pq
import pytest

from golden_landing import (
    NEXT,
    WEEKDAYS,
    Snapshot,
    partition,
    schedule,
    schedule_folder,
    sources,
    trip_updates,
    vehicle_positions,
    write,
    write_empty_like,
)
from transitometer.golden import runner
from transitometer.ingest.sources import Sources

PARAMS = runner.Params(min_events=2)
Q4 = (40.84, -73.95)
STOPS = {f"Q{i}": (40.80 + 0.01 * i, -73.95) for i in range(5)} | {
    "QL": (40.85, -73.95),
    "H0": (40.90, -73.95),
    "H1": (40.91, -73.95),
    "H2": (40.92, -73.95),
}


def _stop_times(
    trip: str, stops_and_times: list[tuple[str, str]]
) -> list[tuple[str, str, str, int]]:
    return [(trip, stop, f"{hhmm}:00", 0) for stop, hhmm in stops_and_times]


def _passes_h1(
    trip: str, observed: str, before: str, after: str, h2: str, vehicle: str
) -> list[Snapshot]:
    """A route-H trip listed with H1 at `observed` until `before`, then only H2 from `after`."""
    return [
        (trip, before, [("H1", observed), ("H2", h2)], vehicle),
        (trip, after, [("H2", h2)], vehicle),
    ]


def build_landing(landing: Path) -> Sources:
    config, bus_sched, sub_sched = sources()
    q = [f"Q{i}" for i in range(5)]
    trips: dict[str, tuple[str, int, str]] = {
        "T1": ("Q", 0, "WKD"),
        "T2": ("Q", 0, "WKD"),
        "T3": ("Q", 0, "WKD"),
        "T4": ("Q", 0, "ADD"),  # added by a calendar exception on the golden day
        "T5": ("Q", 0, "REM"),  # removed by a calendar exception on the golden day
        "T6": ("Q", 0, "SAT"),  # Saturdays only
        "T7": ("Q", 0, "WKD"),
        "T10": ("Q", 0, "WKD"),
        "T11": ("Q", 0, "WKD"),
        "T12": ("Q", 0, "WKD"),
        "T13": ("Q", 0, "WKD"),
        "T14": ("Q", 0, "WKD"),
        "T15": ("Q", 0, "WKD"),
    } | {trip: ("H", 0, "WKD") for trip in ("HA", "HB", "HC", "HD", "HF")}
    stop_times = (
        _stop_times("T1", list(zip(q, ["08:00", "08:10", "08:20", "08:30", "08:40"], strict=True)))
        + _stop_times(
            "T2", list(zip(q, ["08:20", "08:30", "08:40", "08:50", "09:00"], strict=True))
        )
        + _stop_times("T3", [("Q0", "08:40"), ("Q1", "08:50"), ("Q4", "09:00")])
        + _stop_times("T4", [("Q0", "09:00"), ("Q1", "09:10"), ("Q4", "09:20")])
        + _stop_times("T5", [("Q0", "08:00"), ("Q1", "08:10"), ("Q4", "08:20")])
        + _stop_times("T6", [("Q0", "08:00"), ("Q1", "08:10"), ("Q4", "08:20")])
        + _stop_times("T7", [("Q0", "23:00"), ("Q1", "23:10"), ("Q4", "23:20")])
        + _stop_times("T10", [("Q0", "10:00"), ("Q1", "10:10"), ("Q2", "10:20"), ("Q4", "10:30")])
        # T11 visits QL twice (a loop): QL is ambiguous and never scored.
        + _stop_times(
            "T11",
            [("Q0", "11:00"), ("QL", "11:10"), ("Q1", "11:20"), ("QL", "11:30"), ("Q4", "11:40")],
        )
        + _stop_times("T12", [("Q0", "09:00"), ("Q1", "09:10"), ("Q2", "09:20"), ("Q4", "09:30")])
        + _stop_times("T13", [("Q0", "09:30"), ("Q1", "09:40"), ("Q4", "09:50")])
        + _stop_times("T14", [("Q0", "11:40"), ("Q1", "11:50"), ("Q4", "12:00")])
        + _stop_times(
            "T15",
            [
                ("Q0", "07:10"),
                ("Q1", "07:20"),
                ("Q2", "07:30"),
                ("Q3", "07:40"),
                ("QL", "07:50"),
                ("Q4", "08:00"),
            ],
        )
        + [
            row
            for trip, h1 in (("HA", 20), ("HB", 30), ("HC", 40), ("HD", 50), ("HF", 60))
            for row in _stop_times(
                trip,
                [
                    ("H0", f"10:{h1 - 10:02d}"),
                    ("H1", f"{10 + h1 // 60}:{h1 % 60:02d}"),
                    ("H2", f"{10 + (h1 + 10) // 60}:{(h1 + 10) % 60:02d}"),
                ],
            )
        ]
    )
    schedule(
        schedule_folder(landing, bus_sched),
        trips,
        stop_times,
        STOPS,
        services={"WKD": WEEKDAYS, "ADD": {}, "REM": WEEKDAYS, "SAT": {"saturday": 1}},
        exceptions=[("ADD", "20260922", 1), ("REM", "20260922", 2)],
    )
    schedule(schedule_folder(landing, sub_sched), {}, [], {})

    heartbeat: list[Snapshot] = []
    for minute in range(7 * 60, 12 * 60 + 1, 4):
        hhmm = f"{minute // 60:02d}:{minute % 60:02d}"
        if not 9 * 60 + 56 < minute < 10 * 60 + 8:
            after = minute + 1
            heartbeat.append(("XQ", hhmm, [("Z1", f"{after // 60:02d}:{after % 60:02d}")]))
    snapshots: list[Snapshot] = heartbeat + [
        # T1: Q1 +60, Q2 +120, Q3 +90; Q4 is the last stop (arrival from vehicle positions).
        ("T1", "08:10", [("Q1", "08:11"), ("Q2", "08:22"), ("Q3", "08:31:30"), ("Q4", "08:41")]),
        ("T1", "08:21", [("Q2", "08:22"), ("Q3", "08:31:30"), ("Q4", "08:41")]),
        ("T1", "08:30", [("Q3", "08:31:30"), ("Q4", "08:41")]),
        ("T1", "08:40", [("Q4", "08:41")]),
        # T2: passes Q1 on time, then leaves the feed: 1 of 3 intermediate stops -> partial.
        ("T2", "08:29", [("Q1", "08:30"), ("Q2", "08:40"), ("Q3", "08:50"), ("Q4", "09:00")]),
        ("T2", "08:31", [("Q2", "08:41"), ("Q3", "08:51"), ("Q4", "09:01")]),
        # T11: loop through QL; Q1 on time.
        ("T11", "11:09", [("QL", "11:10"), ("Q1", "11:20"), ("QL", "11:30"), ("Q4", "11:40")]),
        ("T11", "11:19", [("Q1", "11:20"), ("QL", "11:30"), ("Q4", "11:40")]),
        ("T11", "11:29", [("QL", "11:30"), ("Q4", "11:40")]),
        ("T11", "11:39", [("Q4", "11:40")]),
        # T12: Q1 echoed exactly 90 s (still passed); Q2 echoed 91 s (stale); Q4 predicted exactly
        # 300 s after the trip's last snapshot (still terminal).
        ("T12", "09:09", [("Q1", "09:10"), ("Q2", "09:20"), ("Q4", "09:30")]),
        ("T12", "09:11:30", [("Q1", "09:10"), ("Q2", "09:20"), ("Q4", "09:30")]),
        ("T12", "09:19", [("Q2", "09:20"), ("Q4", "09:30")]),
        ("T12", "09:21:31", [("Q2", "09:20"), ("Q4", "09:30")]),
        ("T12", "09:25", [("Q4", "09:30")]),
        # T13: Q4 predicted 301 s after the last snapshot -> unconfirmed.
        ("T13", "09:39", [("Q1", "09:40"), ("Q4", "09:50")]),
        ("T13", "09:41", [("Q4", "09:46:01")]),
        # T14: announced with predictions, then leaves the feed before passing any stop -> not_run.
        ("T14", "11:44", [("Q1", "11:50"), ("Q4", "12:00")]),
        # T15: vehicle VA passes Q1 (0 s), then VB takes over: Q2 +300, skips Q3, QL +300.
        ("T15", "07:19", [("Q1", "07:20"), ("Q2", "07:30")], "VA"),
        ("T15", "07:21", [("Q2", "07:31")], "VA"),
        ("T15", "07:34", [("Q2", "07:35"), ("QL", "07:55"), ("Q4", "08:05")], "VB"),
        ("T15", "07:54", [("QL", "07:55"), ("Q4", "08:05")], "VB"),
        ("T15", "07:58", [("Q4", "08:05")], "VB"),
    ]
    # Route H at H1 (scheduled every 600 s): HB 150 s after HA (bunched, = 0.25 x), HC 1200 s
    # (gap, = 2 x), HD 720 s (regular, = 1.2 x); HF is HD's vehicle again: no headway.
    snapshots += _passes_h1("HA", "10:20", "10:19", "10:21", "10:30", "V-HA")
    snapshots += _passes_h1("HB", "10:22:30", "10:22", "10:23", "10:40", "V-HB")
    snapshots += _passes_h1("HC", "10:42:30", "10:42", "10:43", "10:50", "V-HC")
    snapshots += _passes_h1("HD", "10:54:30", "10:54", "10:55:30", "11:00", "VD")
    snapshots += _passes_h1("HF", "10:55", "10:54:30", "10:56", "11:10", "VD")
    routes = {"XQ": "Z"} | {trip: route for trip, (route, _, _) in trips.items()}
    write(landing / partition("trip_updates", "bus"), trip_updates(snapshots, routes=routes))
    write_empty_like(
        landing / partition("trip_updates", "bus", NEXT), landing / partition("trip_updates", "bus")
    )
    for day in (None, NEXT):
        target = partition("trip_updates", "sub", day) if day else partition("trip_updates", "sub")
        write_empty_like(landing / target, landing / partition("trip_updates", "bus"))

    near, off = (Q4[0] + 0.00027, Q4[1]), (Q4[0] + 0.00072, Q4[1])  # ~30 m and ~80 m north
    vp = vehicle_positions(
        [
            ("T1", "08:05", "Q1", "V-T1", Q4),  # at the last stop before the trip ran: ignored
            ("T1", "08:40:30", "Q4", "V-T1", off),  # outside the 50 m radius
            ("T1", "08:41", "Q4", "V-T1", near),  # arrival: +60 s
            ("T1", "08:43", "Q4", "V-T1", Q4),
        ]
    )
    write(landing / partition("vehicle_positions", "bus"), vp)
    write_empty_like(
        landing / partition("vehicle_positions", "bus", NEXT),
        landing / partition("vehicle_positions", "bus"),
    )
    return config


@pytest.fixture(scope="module")
def landing_root(tmp_path_factory: pytest.TempPathFactory) -> tuple[Sources, Path]:
    root = tmp_path_factory.mktemp("golden_kpis")
    return build_landing(root / "landing"), root


@pytest.fixture(scope="module")
def golden(landing_root: tuple[Sources, Path]) -> runner.GoldenResult:
    config, root = landing_root
    return runner.run(config, root / "landing", root / "out", params=PARAMS, memory_limit="1GB")


def _table(result: runner.GoldenResult, name: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = pq.read_table(result.out_dir / f"{name}.parquet").to_pylist()
    return rows


def _statuses(config: Sources, landing: Path) -> dict[tuple[str, str], str]:
    """Stop-event status per (trip, stop), straight from the first two SQL steps."""
    values = {**runner._inputs(config, landing), **vars(PARAMS)}
    with duckdb.connect() as con:
        for step in ("01_schedule.sql", "02_stop_events.sql"):
            con.execute(runner.render(step, values))
        rows = con.execute("SELECT trip_id, stop_id, status FROM observed_events").fetchall()
    return {(trip, stop): status for trip, stop, status in rows}


def test_stale_and_terminal_edges(landing_root: tuple[Sources, Path]) -> None:
    config, root = landing_root
    status = _statuses(config, root / "landing")
    assert status[("T12", "Q1")] == "passed"  # echoed exactly max_stale_s
    assert status[("T12", "Q2")] == "stale"  # one second more
    assert status[("T12", "Q4")] == "terminal"  # exactly terminal_grace_s ahead
    assert status[("T13", "Q4")] == "unconfirmed"  # one second more


def test_stale_events_reported_by_position(golden: runner.GoldenResult) -> None:
    rows = golden.summary["stale_summary"]
    assert [(r["position"], r["stale_events"], r["median_staleness_s"]) for r in rows] == [
        ("intermediate", 1, 91)
    ]


def test_loop_stop_and_calendar_exceptions(golden: runner.GoldenResult) -> None:
    events = {(r["trip_id"], r["stop_id"]) for r in _table(golden, "stop_events")}
    assert ("T11", "Q1") in events and ("T11", "QL") not in events
    delivery = {r["trip_id"]: r["delivery"] for r in _table(golden, "trip_delivery")}
    assert "T4" in delivery  # added service on the golden day is scheduled
    assert "T5" not in delivery and "T6" not in delivery  # removed / Saturday-only service


def test_missing_trip_classes(golden: runner.GoldenResult) -> None:
    delivery = {r["trip_id"]: r["delivery"] for r in _table(golden, "trip_delivery")}
    assert delivery == {
        "T1": "delivered",
        "T2": "partial",  # 1 of 3 intermediate stops passed
        "T3": "missing",
        "T4": "missing",
        "T7": "unknown",  # scheduled after the last snapshot
        "T10": "unknown",  # overlaps the 720 s outage
        "T11": "delivered",
        "T12": "delivered",  # Q1 passed = 1 of 2 intermediate stops
        "T13": "delivered",
        "T14": "not_run",  # reported, never observed moving
        "T15": "delivered",  # Q1, Q2, QL of 4 intermediate stops, across two vehicles
        "HA": "delivered",
        "HB": "delivered",
        "HC": "delivered",
        "HD": "delivered",
        "HF": "delivered",
    }
    (summary,) = golden.summary["missing_trip_summary"]
    assert (summary["scheduled"], summary["delivered"], summary["partial"]) == (16, 10, 1)
    assert (summary["missing"], summary["not_run"], summary["unknown"]) == (2, 1, 2)
    assert (summary["missing_share"], summary["not_delivered_share"]) == (0.1429, 0.2143)
    by_route = {r["route_id"]: r for r in _table(golden, "missing_by_route")}
    assert by_route["Q"]["missing"] == 2 and by_route["H"]["delivered"] == 5


def test_segments_and_delay_attribution(golden: runner.GoldenResult) -> None:
    segments = {
        (r["from_stop"], r["to_stop"]): r
        for r in _table(golden, "segments")
        if r["static_trip_id"] == "T1"
    }
    assert {
        k: (v["sched_travel_s"], v["observed_travel_s"], v["excess_s"]) for k, v in segments.items()
    } == {
        ("Q1", "Q2"): (600, 660, 60),
        ("Q2", "Q3"): (600, 570, -30),
    }
    trips = {r["static_trip_id"]: r for r in _table(golden, "trip_delay_attribution")}
    t1 = trips["T1"]
    assert (t1["inherited_delay_s"], t1["gained_delay_s"], t1["final_delay_s"]) == (60, 30, 90)
    # The invariant, for every trip: final delay = inherited + gained along the way.
    assert all(
        r["final_delay_s"] == r["inherited_delay_s"] + r["gained_delay_s"] for r in trips.values()
    )
    assert all(
        r["attribution_mismatches"] == 0 for r in golden.summary["delay_attribution_summary"]
    )
    stats = {
        (r["from_stop"], r["to_stop"], r["service_hour"]): r
        for r in _table(golden, "segment_travel_stats")
    }
    assert stats[("Q1", "Q2", 8)]["p50_travel_s"] == 660


def test_headway_ratio_edges_and_same_vehicle(golden: runner.GoldenResult) -> None:
    rows = {r["trip_id"]: r for r in _table(golden, "headways") if r["stop_id"] == "H1"}
    assert {k: (v["headway_s"], v["headway_class"]) for k, v in rows.items()} == {
        "HB": (150, "bunched"),
        "HC": (1200, "gap"),
        "HD": (720, "regular"),
    }


def test_terminal_arrivals_from_vehicle_positions(golden: runner.GoldenResult) -> None:
    (event,) = [r for r in _table(golden, "terminal_events") if r["observations"] == 1]
    assert (event["static_trip_id"], event["stop_id"], event["delay_s"]) == ("T1", "Q4", 60)
    (summary,) = golden.summary["terminal_summary"]
    assert (summary["matched_trips"], summary["measured"]) == (12, 1)
    otp = {r["scope"]: r for r in golden.summary["otp_summary"]}
    assert (otp["terminals"]["events"], otp["terminals"]["on_time_share"]) == (1, 1.0)


def _wilson(k: int, n: int) -> tuple[float, float]:
    z = 1.959963984540054
    p = k / n
    centre = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - half) / (1 + z * z / n), (centre + half) / (1 + z * z / n)


def test_stop_hour_reliability_matches_on_time_events(golden: runner.GoldenResult) -> None:
    counts: dict[tuple[Any, ...], list[int]] = defaultdict(lambda: [0, 0])
    for e in _table(golden, "stop_events"):
        key = (e["route_id"], e["direction_id"], e["stop_id"], e["service_hour"])
        counts[key][0] += 1
        counts[key][1] += int(-60 <= e["delay_s"] <= 300)
    cells = {
        (r["route_id"], r["direction_id"], r["stop_id"], r["service_hour"]): r
        for r in _table(golden, "stop_hour_reliability")
    }
    assert {k: [v["events"], v["on_time"]] for k, v in cells.items()} == dict(counts)
    q1 = cells[("Q", 0, "Q1", 8)]  # T1 (+60) and T2 (0)
    assert (q1["events"], q1["on_time"], q1["sufficient"]) == (2, 2, True)
    low, high = _wilson(2, 2)
    assert (q1["ci_low"], q1["ci_high"]) == (round(low, 4), round(high, 4))


def _poisson1(u: int) -> int:
    thresholds = (1580030168, 3160060337, 3950075421, 4213413783, 4279248373, 4292415291,
                  4294609777, 4294923276)  # fmt: skip
    return next((k for k, limit in enumerate(thresholds) if u < limit), 8)


def _quantile_cont(values: list[float], q: float) -> float:
    ordered = sorted(values)
    position = q * (len(ordered) - 1)
    lower = math.floor(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def test_route_bootstrap_ci_recomputed_independently(golden: runner.GoldenResult) -> None:
    trips: dict[tuple[str, str, str, str], list[int]] = defaultdict(lambda: [0, 0])
    for e in _table(golden, "stop_events"):
        key = (e["grp"], e["route_id"], e["service_date"], e["static_trip_id"])
        trips[key][0] += 1
        trips[key][1] += int(-60 <= e["delay_s"] <= 300)
    shares: dict[tuple[str, str], list[float]] = defaultdict(list)
    for b in range(1, PARAMS.bootstrap_resamples + 1):
        totals: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
        for (grp, route, day, trip), (n, k) in trips.items():
            text = f"{PARAMS.bootstrap_seed}|{b}|{grp}|{day}|{trip}"
            w = _poisson1(int(hashlib.md5(text.encode()).hexdigest()[:8], 16))
            totals[(grp, route)][0] += w * n
            totals[(grp, route)][1] += w * k
        for route_key, (wn, wk) in totals.items():
            if wn > 0:
                shares[route_key].append(wk / wn)
    scorecard = _table(golden, "route_scorecard")
    # Q: 7 of 7 events on time; H: HB and HF early -> 3 of 5.
    assert {r["route_id"]: (r["on_time_share"], r["rank"]) for r in scorecard} == {
        "Q": (1.0, 1),
        "H": (0.6, 2),
    }
    for row in scorecard:
        values = shares[(row["grp"], row["route_id"])]
        assert len(values) > PARAMS.bootstrap_resamples * 0.9
        assert row["ci_low"] == round(_quantile_cont(values, 0.025), 4)
        assert row["ci_high"] == round(_quantile_cont(values, 0.975), 4)
        assert row["ci_low"] <= row["on_time_share"] <= row["ci_high"]
        assert row["rank_low"] <= row["rank"] <= row["rank_high"]


def test_outage_threshold_is_strict(landing_root: tuple[Sources, Path]) -> None:
    """The 09:56 -> 10:08 gap is exactly 720 s: with a 720 s threshold it is not an outage."""
    config, root = landing_root
    params = dataclasses.replace(PARAMS, outage_gap_s=720)
    result = runner.run(
        config, root / "landing", root / "out720", params=params, memory_limit="1GB"
    )
    delivery = {r["trip_id"]: r["delivery"] for r in _table(result, "trip_delivery")}
    assert delivery["T10"] == "missing"


def test_segments_never_cross_a_vehicle_change(golden: runner.GoldenResult) -> None:
    segments = [r for r in _table(golden, "segments") if r["static_trip_id"] == "T15"]
    assert [
        (r["unit"], r["from_stop"], r["to_stop"], r["hops"], r["excess_s"]) for r in segments
    ] == [("VB", "Q2", "QL", 2, 0)]
    trips = {
        r["unit"]: r
        for r in _table(golden, "trip_delay_attribution")
        if r["static_trip_id"] == "T15"
    }
    assert {
        u: (r["inherited_delay_s"], r["gained_delay_s"], r["final_delay_s"])
        for u, r in trips.items()
    } == {
        "VA": (0, 0, 0),
        "VB": (300, 0, 300),
    }


def test_route_hour_scorecard_needs_enough_trips(golden: runner.GoldenResult) -> None:
    cells = {(r["route_id"], r["service_hour"]): r for r in _table(golden, "route_hour_scorecard")}
    q8 = cells[("Q", 8)]  # T1 (3 events) and T2 (1 event): 2 trips < min_trips
    assert (q8["events"], q8["trips"], q8["on_time_share"], q8["sufficient"]) == (4, 2, 1.0, False)
    h10 = cells[("H", 10)]  # HA, HB, HC, HD
    assert (h10["events"], h10["trips"], h10["on_time_share"]) == (4, 4, 0.75)
    assert all(r["ci_low"] <= r["on_time_share"] <= r["ci_high"] for r in cells.values())
    routes = {r["route_id"]: r for r in _table(golden, "route_scorecard")}
    assert routes["Q"]["trips"] == 6 and routes["Q"]["sufficient"]  # T1, T2, T11-T13, T15
