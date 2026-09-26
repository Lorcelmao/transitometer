"""Golden SQL on a hand-built landing zone where every expected value is computed by hand.

Service day 2026-09-22 (Tuesday, EDT): local midnight = 1_790_049_600 UTC epoch. Every bus trip
has an origin stop S0 (never listed by the feed) and intermediate stops S1/S2; S3 is a terminal.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import pyarrow.parquet as pq
import pytest

from golden_landing import (
    NEXT,
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

SUB_1 = "AFA-Weekday-00_048000_1..S03R"
SUB_7 = "AFA-Weekday-00_050000_7..N35R"
SUB_4 = "AFA-Weekday-00_150700_4..N13R"  # starts 25:07, after midnight
SUB_6 = "AFA-Weekday-00_143900_6..N01R"  # starts 23:59, before midnight


def _bus_trip(trip: str, times: list[str]) -> list[tuple[str, str, str, int]]:
    """S0 origin, S1.. in order; S1 and S3 are timepoints."""
    return [
        (trip, f"S{i}", f"{hhmm}:00", 1 if i in (0, 1, 3) else 0) for i, hhmm in enumerate(times)
    ]


def build_landing(landing: Path) -> Sources:
    config, bus_sched, sub_sched = sources()

    bus_trips = {
        "B1": ["07:55", "08:00", "08:10", "08:20"],
        "B2": ["08:05", "08:10", "08:20", "08:30"],
        "B5": ["08:15", "08:20", "08:30"],
        "B8": ["08:25", "08:30", "08:40", "08:50"],
        "B6": ["08:35", "08:40", "08:50"],
        "B7": ["08:45", "08:50", "09:00"],
        "B4": ["08:55", "09:00", "09:10"],
        "B10": ["08:50", "08:55", "09:05"],
        "B9": ["09:25", "09:30", "09:40", "09:50"],
        "B3": ["25:05", "25:10", "25:20"],
    }
    schedule(
        schedule_folder(landing, bus_sched),
        {trip: ("R", 0) for trip in bus_trips},
        [row for trip, times in bus_trips.items() for row in _bus_trip(trip, times)],
        {f"S{i}": (40.70 + 0.01 * i, -73.90) for i in range(4)},
    )
    schedule(
        schedule_folder(landing, sub_sched),
        {SUB_1: ("1", 1), SUB_7: ("7", 0), SUB_4: ("4", 0), SUB_6: ("6", 0)},
        [
            (SUB_1, "100S", "07:55:00", 0),
            (SUB_1, "101S", "08:00:00", 0),
            (SUB_1, "102S", "08:05:00", 0),
            (SUB_1, "104S", "08:10:00", 0),
            (SUB_7, "700N", "08:15:00", 0),
            (SUB_7, "701N", "08:20:00", 0),
            (SUB_7, "702N", "08:25:00", 0),
            (SUB_7, "703N", "08:30:00", 0),
            (SUB_4, "401N", "25:07:00", 0),
            (SUB_4, "402N", "25:12:00", 0),
            (SUB_4, "403N", "25:17:00", 0),
            (SUB_6, "601N", "23:59:00", 0),
            (SUB_6, "602N", "24:04:00", 0),
            (SUB_6, "603N", "24:09:00", 0),
        ],
        {},
    )

    write(
        landing / partition("trip_updates", "bus"),
        trip_updates(
            [
                # B1: S1 passed (0 s); S2 passed with a prediction exactly 180 s ahead (+120 s);
                # S3 terminal (excluded from KPIs as a terminal).
                ("B1", "07:59", [("S1", "08:00"), ("S2", "08:10"), ("S3", "08:20")]),
                # same vehicle and snapshot, a later second prediction for S1 must win -> +20 s
                ("B1", "07:59", [("S1", "08:00:20")]),
                ("B1", "08:09", [("S2", "08:12"), ("S3", "08:22")]),
                ("B1", "08:24", [("S3", "08:27")]),
                # B2: S1 passed (+30 s); trip vanishes with S2, S3 pending -> unconfirmed
                ("B2", "08:09", [("S1", "08:10:30"), ("S2", "08:20"), ("S3", "08:30")]),
                ("B2", "08:18", [("S2", "08:21"), ("S3", "08:31")]),
                # B5: S1 at 08:11:30 (-510 s, early) one minute behind B2 -> bunched
                ("B5", "08:10", [("S1", "08:11:30"), ("S2", "08:30")]),
                ("B5", "08:12", [("S2", "08:31")]),
                # B8: S1 +300 s (on-time edge), S2 +301 s (late edge), S3 terminal
                ("B8", "08:34", [("S1", "08:35"), ("S2", "08:45:01"), ("S3", "09:00")]),
                ("B8", "08:44", [("S2", "08:45:01"), ("S3", "09:00")]),
                ("B8", "08:58", [("S3", "09:00")]),
                # B6: S1 time echoed 120 s after it passed -> stale
                ("B6", "08:38", [("S1", "08:40"), ("S2", "08:50")]),
                ("B6", "08:42", [("S1", "08:40"), ("S2", "08:50")]),
                ("B6", "08:43", [("S2", "08:51")]),
                # B7 has two vehicles: V2 passes S1 first (08:50:30) and is kept; V1 (08:51) is not
                ("B7", "08:49", [("S1", "08:51"), ("S2", "09:01")], "V1"),
                ("B7", "08:52", [("S2", "09:02")], "V1"),
                ("B7", "08:58", [("S2", "09:02")], "V1"),
                ("B7", "08:49", [("S1", "08:50:30"), ("S2", "09:00")], "V2"),
                ("B7", "08:51", [("S2", "09:01")], "V2"),
                # B10: S1 at 08:50 (-300 s, early), 900 s after B8 -> irregular headway
                ("B10", "08:48", [("S1", "08:50"), ("S2", "09:00")]),
                ("B10", "08:52", [("S2", "09:01")]),
                # B4: S1 dropped while predicted 10 min ahead -> implausible
                ("B4", "08:50", [("S1", "09:00"), ("S2", "09:10")]),
                ("B4", "08:52", [("S2", "09:10")]),
                # B9: S1 -60 s (on-time edge), S2 -61 s (early edge), S3 terminal
                ("B9", "09:28", [("S1", "09:29"), ("S2", "09:38:59"), ("S3", "09:50")]),
                ("B9", "09:38", [("S2", "09:38:59"), ("S3", "09:50")]),
                ("B9", "09:47", [("S3", "09:50")]),
                # X9: not in the schedule -> unscheduled
                ("X9", "08:00", [("S1", "08:01"), ("S2", "08:05")]),
                ("X9", "08:03", [("S2", "08:05")]),
            ]
        ),
    )
    # B3 runs past midnight (25:10 = 01:10 next calendar day): next UTC archive partition.
    write(
        landing / partition("trip_updates", "bus", NEXT),
        trip_updates(
            [
                ("B3", "25:09", [("S1", "25:10:30"), ("S2", "25:20")]),
                ("B3", "25:15", [("S2", "25:21")]),
            ]
        ),
    )
    write(
        landing / partition("trip_updates", "sub"),
        trip_updates(
            [
                # 1 train: origin 100S observed (echo, excluded), 101S +30, 102S +60, 104S terminal
                (
                    "048000_1..S03R",
                    "07:54",
                    [("100S", "07:55"), ("101S", "08:00:30"), ("102S", "08:05"), ("104S", "08:10")],
                ),
                (
                    "048000_1..S03R",
                    "07:59",
                    [("101S", "08:00:30"), ("102S", "08:05"), ("104S", "08:10")],
                ),
                ("048000_1..S03R", "08:03", [("102S", "08:06"), ("104S", "08:11")]),
                ("048000_1..S03R", "08:06", [("104S", "08:11")]),
                # 7 train (no path code in the id -> route_direction tier): 701N +60, 702N +120
                ("050000_7..N", "08:19", [("701N", "08:21"), ("702N", "08:26"), ("703N", "08:31")]),
                ("050000_7..N", "08:25", [("702N", "08:27"), ("703N", "08:31")]),
                ("050000_7..N", "08:26", [("703N", "08:31")]),
            ],
            subway_ids=True,
        ),
    )
    # NYCT labels a trip that starts after midnight with the calendar date, not its service day;
    # a trip that starts at 23:59 keeps its date even though it runs past midnight.
    after_midnight = trip_updates(
        [
            ("150700_4..N13R", "25:11", [("402N", "25:12:30"), ("403N", "25:17")]),
            ("150700_4..N13R", "25:14", [("403N", "25:17")]),
        ],
        subway_ids=True,
        start_date="20260923",
    )
    before_midnight = trip_updates(
        [
            ("143900_6..N01R", "24:03", [("602N", "24:04:30"), ("603N", "24:09")]),
            ("143900_6..N01R", "24:06", [("603N", "24:09")]),
        ],
        subway_ids=True,
    )
    write(
        landing / partition("trip_updates", "sub", NEXT),
        {k: after_midnight[k] + before_midnight[k] for k in after_midnight},
    )
    vp = vehicle_positions(
        [
            ("B1", "07:59", "S1", "V-B1", None),
            ("B1", "08:01", "S2", "V-B1", None),
            ("B1", "08:12:30", "S3", "V-B1", None),
            ("B2", "08:09", "S1", "V-B2", None),
            ("B2", "08:11", "S2", "V-B2", None),
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
    root = tmp_path_factory.mktemp("golden")
    return build_landing(root / "landing"), root


@pytest.fixture(scope="module")
def golden(landing_root: tuple[Sources, Path]) -> runner.GoldenResult:
    sources, root = landing_root
    return runner.run(sources, root / "landing", root / "out", memory_limit="1GB")


def _table(result: runner.GoldenResult, name: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = pq.read_table(result.out_dir / f"{name}.parquet").to_pylist()
    return rows


def test_stop_event_statuses(golden: runner.GoldenResult) -> None:
    status = {(r["grp"], r["status"]): r["events"] for r in golden.summary["event_status_summary"]}
    # passed: B1 S1,S2; B2 S1; B5 S1; B7 S1 (V1, V2); B8 S1,S2; B9 S1,S2; B10 S1; X9 S1; B3 S1
    assert status[("bus", "passed")] == 13
    assert status[("bus", "terminal")] == 5  # B1 S3; B7 S2 (V1); B8 S3; B9 S3; X9 S2
    assert (
        status[("bus", "unconfirmed")] == 8
    )  # B2 S2,S3; B5 S2; B4 S2; B6 S2; B7 S2 (V2); B10 S2; B3 S2
    assert status[("bus", "implausible")] == 1  # B4 S1
    assert status[("bus", "stale")] == 1  # B6 S1
    # subway passed: 100S (origin echo), 101S, 102S, 701N, 702N, 402N, 602N;
    # terminal: 104S, 703N, 403N, 603N
    assert status[("subway", "passed")] == 7 and status[("subway", "terminal")] == 4


def test_trip_matching_tiers_and_multi_vehicle_trips(golden: runner.GoldenResult) -> None:
    tiers = {(r["grp"], r["tier"]): r["rt_trips"] for r in golden.summary["trip_match_summary"]}
    assert tiers[("bus", "exact")] == 10 and tiers[("bus", "unscheduled")] == 1
    # The 25:07 train reported under the next calendar date still matches its own service day.
    assert tiers[("subway", "suffix")] == 3 and tiers[("subway", "route_direction")] == 1
    multi = {r["grp"]: r for r in golden.summary["multi_unit_summary"]}
    assert (multi["bus"]["rt_trips"], multi["bus"]["multi_unit_trips"]) == (11, 1)


def test_kpi_events_exclude_ambiguous_trip_stops(golden: runner.GoldenResult) -> None:
    events = {(r["trip_id"], r["stop_id"]): r for r in _table(golden, "stop_events")}
    assert {k: v["delay_s"] for k, v in events.items()} == {
        ("B1", "S1"): 20,
        ("B1", "S2"): 120,
        ("B2", "S1"): 30,
        ("B5", "S1"): -510,
        ("B8", "S1"): 300,
        ("B8", "S2"): 301,
        ("B9", "S1"): -60,
        ("B9", "S2"): -61,
        ("B10", "S1"): -300,
        ("B3", "S1"): 30,
        ("048000_1..S03R", "101S"): 30,
        ("048000_1..S03R", "102S"): 60,
        ("050000_7..N", "701N"): 60,
        ("050000_7..N", "702N"): 120,
        ("150700_4..N13R", "402N"): 30,
        ("143900_6..N01R", "602N"): 30,
    }
    assert all(v["observations"] == 1 for v in events.values())
    # B7 S1 was passed by two vehicles (V1 08:51, V2 08:50:30): ambiguous, reported not scored.
    ambiguous = {r["grp"]: r for r in golden.summary["ambiguous_summary"]}
    assert (ambiguous["bus"]["trip_stops"], ambiguous["bus"]["ambiguous_trip_stops"]) == (11, 1)


def test_origin_and_terminal_reported_not_scored(golden: runner.GoldenResult) -> None:
    ends = {(r["grp"], r["position"]): r for r in golden.summary["end_of_trip_summary"]}
    assert ends[("subway", "origin")]["events"] == 1
    assert ends[("subway", "origin")]["zero_delay_share"] == 1.0  # timetable echo
    assert ends[("bus", "terminal")]["events"] == 4  # B1, B7 (V1), B8, B9
    assert ends[("subway", "terminal")]["events"] == 4


def test_otp_band_edges_and_timepoints(golden: runner.GoldenResult) -> None:
    otp = {(r["grp"], r["scope"]): r for r in golden.summary["otp_summary"]}
    bus = otp[("bus", "all_stops")]
    assert bus["events"] == 10
    assert (bus["on_time_share"], bus["early_share"], bus["late_share"]) == (0.6, 0.3, 0.1)
    timepoints = otp[("bus", "timepoints")]  # only S1 rows are timepoints
    assert timepoints["events"] == 7
    assert timepoints["on_time_share"] == pytest.approx(5 / 7, abs=1e-4)
    assert otp[("subway", "all_stops")]["on_time_share"] == 1.0


def test_headway_classes(golden: runner.GoldenResult) -> None:
    rows = {(r["trip_id"], r["stop_id"]): r for r in _table(golden, "headways")}
    # Unscheduled X9 (08:01) is a real passage between B1 (08:00:20) and B2 (08:10:30).
    assert (rows[("X9", "S1")]["headway_s"], rows[("X9", "S1")]["source"]) == (40, "unscheduled")
    assert rows[("X9", "S1")]["headway_class"] == "bunched"
    assert (rows[("B2", "S1")]["headway_s"], rows[("B2", "S1")]["ref_headway_s"]) == (570, 600)
    assert rows[("B2", "S1")]["headway_class"] == "regular"
    assert (rows[("B5", "S1")]["headway_s"], rows[("B5", "S1")]["headway_class"]) == (60, "bunched")
    assert (rows[("B8", "S1")]["headway_s"], rows[("B8", "S1")]["headway_class"]) == (1410, "gap")
    assert (rows[("B10", "S1")]["headway_s"], rows[("B10", "S1")]["headway_class"]) == (
        900,
        "irregular",
    )
    # B7's S1 is ambiguous (two vehicles), yet its first passage still follows B10 in the sequence.
    assert (rows[("B7", "S1")]["headway_s"], rows[("B7", "S1")]["source"]) == (30, "ambiguous")


def test_vehicle_position_crosscheck(golden: runner.GoldenResult) -> None:
    (summary,) = golden.summary["crosscheck_summary"]
    assert summary["compared"] == 3 and summary["agreement_share"] == 1.0


def test_rerun_is_byte_identical(
    golden: runner.GoldenResult, landing_root: tuple[Sources, Path]
) -> None:
    sources, root = landing_root
    again = runner.run(sources, root / "landing", root / "rerun", memory_limit="1GB", threads=3)
    assert again.checksums == golden.checksums
    for name, digest in golden.checksums.items():
        assert hashlib.sha256((golden.out_dir / name).read_bytes()).hexdigest() == digest


@pytest.mark.parametrize(
    ("service_date", "utc_base"),
    [
        ("20260922", datetime(2026, 9, 22, 4, tzinfo=timezone.utc)),  # EDT
        ("20261101", datetime(2026, 11, 1, 5, tzinfo=timezone.utc)),  # fall back: noon EST - 12h
        (
            "20260308",
            datetime(2026, 3, 8, 4, tzinfo=timezone.utc),
        ),  # spring forward: noon EDT - 12h
    ],
)
def test_service_day_base_handles_dst(service_date: str, utc_base: datetime) -> None:
    keys = (
        "service_dates",
        "bus_calendar",
        "subway_calendar",
        "bus_calendar_dates",
        "subway_calendar_dates",
        "bus_trips",
        "subway_trips",
        "bus_stop_times",
        "subway_stop_times",
    )
    values = {k: "[]" for k in keys} | {"timezone": "America/New_York"}
    macros = [s for s in runner.render("01_schedule.sql", values).split(";") if "MACRO" in s]
    with duckdb.connect() as con:
        for statement in macros:
            con.execute(statement)
        (base,) = con.execute(f"SELECT day_base('{service_date}')").fetchone() or (0,)
    assert base == int(utc_base.timestamp())
