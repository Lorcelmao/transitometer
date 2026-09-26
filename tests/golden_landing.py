"""Builders for small hand-made landing zones on which the golden SQL is checked by hand.

Service day 2026-09-22 (Tuesday, EDT): local midnight = 1_790_049_600 UTC epoch.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from transitometer.ingest.sources import (
    DateRange,
    RealtimeFeed,
    ScheduleVersion,
    Sources,
    realtime_relpath,
    schedule_dir,
)

DAY = date(2026, 9, 22)
NEXT = date(2026, 9, 23)
BASE = 1_790_049_600  # 2026-09-22 00:00 America/New_York
FETCH_LAG_S = 5  # the archive fetched every snapshot this long after its header timestamp
SCHEDULE_TABLES = (
    "calendar.parquet",
    "calendar_dates.parquet",
    "trips.parquet",
    "stop_times.parquet",
    "stops.parquet",
)
WEEKDAYS = {"monday": 1, "tuesday": 1, "wednesday": 1, "thursday": 1, "friday": 1}

# (trip, feed_time, [(stop, predicted), ...][, vehicle])
Snapshot = tuple[str, str, list[tuple[str, str]]] | tuple[str, str, list[tuple[str, str]], str]


def t(hhmm: str) -> int:
    """'HH:MM' or 'HH:MM:SS' (may exceed 24h) -> epoch seconds on the service day."""
    parts = [int(p) for p in hhmm.split(":")] + [0]
    return BASE + parts[0] * 3600 + parts[1] * 60 + parts[2]


def fetched(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch + FETCH_LAG_S, tz=timezone.utc)


def write(path: Path, rows: Mapping[str, Sequence[object]] | pa.Table) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(rows if isinstance(rows, pa.Table) else pa.table(rows), path)


def write_empty_like(path: Path, like: Path) -> None:
    """An archive partition with no rows but the same (typed) schema as `like`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pq.read_schema(like).empty_table(), path)


def trip_updates(
    snapshots: list[Snapshot],
    subway_ids: bool = False,
    routes: Mapping[str, str] | None = None,
    start_date: str = "20260922",
) -> dict[str, list[Any]]:
    """Snapshots -> trip-update rows. Route 'R' unless `routes` maps the trip elsewhere.

    subway_ids mimics NYCT: no vehicle_id, and entity_id is the entity's position in its snapshot.
    """
    cols: dict[str, list[Any]] = {
        k: []
        for k in (
            "source_file",
            "feed_timestamp",
            "fetch_timestamp",
            "entity_id",
            "trip_id",
            "vehicle_id",
            "start_date",
            "route_id",
            "stop_id",
            "stop_sequence",
            "arrival_time",
            "departure_time",
        )
    }
    position: dict[str, int] = {}
    for snap in snapshots:
        trip, feed_time, stops = snap[0], snap[1], snap[2]
        vehicle = snap[3] if len(snap) == 4 else f"V-{trip}"
        position[feed_time] = position.get(feed_time, 0) + 1
        for seq, (stop, predicted) in enumerate(stops, start=1):
            cols["source_file"].append(f"{feed_time}.pb")
            cols["feed_timestamp"].append(t(feed_time))
            cols["fetch_timestamp"].append(fetched(t(feed_time)))
            cols["entity_id"].append(
                f"{position[feed_time]:06d}" if subway_ids else f"E-{trip}-{vehicle}"
            )
            cols["trip_id"].append(trip)
            cols["vehicle_id"].append(None if subway_ids else vehicle)
            cols["start_date"].append(start_date)
            cols["route_id"].append((routes or {}).get(trip, "R"))
            cols["stop_id"].append(stop)
            cols["stop_sequence"].append(seq)
            cols["arrival_time"].append(t(predicted))
            cols["departure_time"].append(t(predicted))
    return cols


def vehicle_positions(
    rows: list[tuple[str, str, str | None, str, tuple[float, float] | None]],
    fix_ages: Sequence[int] | None = None,
) -> pa.Table:
    """[(trip, time, next stop, vehicle, (lat, lon) or None), ...] -> vehicle-position rows.

    `time` is the snapshot time; each fix is `fix_ages[i]` seconds older (default 0)."""
    ages = list(fix_ages) if fix_ages is not None else [0] * len(rows)
    return pa.table(
        {
            "feed_timestamp": pa.array([t(r[1]) for r in rows], pa.uint64()),
            "fetch_timestamp": [fetched(t(r[1])) for r in rows],
            "timestamp": pa.array(
                [t(r[1]) - a for r, a in zip(rows, ages, strict=True)], pa.uint64()
            ),
            "trip_id": [r[0] for r in rows],
            "vehicle_id": [r[3] for r in rows],
            "start_date": ["20260922"] * len(rows),
            "stop_id": pa.array([r[2] for r in rows], pa.string()),
            "latitude": pa.array([r[4][0] if r[4] else None for r in rows], pa.float32()),
            "longitude": pa.array([r[4][1] if r[4] else None for r in rows], pa.float32()),
        }
    )


def _strings(values: Sequence[object]) -> pa.Array:
    return pa.array([None if v is None else str(v) for v in values], pa.string())


def schedule(
    folder: Path,
    trips: Mapping[str, tuple[str, int] | tuple[str, int, str]],
    stop_times: list[tuple[str, str, str, int]],
    stops: Mapping[str, tuple[float, float]],
    services: Mapping[str, Mapping[str, int]] | None = None,
    exceptions: Sequence[tuple[str, str, int]] = (("WKD", "20261225", 2),),
) -> None:
    """trips: trip_id -> (route_id, direction_id[, service_id='WKD']);
    stop_times: (trip, stop, 'HH:MM:SS', timepoint), in stop order per trip;
    services: service_id -> {weekday name: 1}, all valid 2026-09-01..2026-12-31;
    exceptions: (service_id, 'YYYYMMDD', 1 = added | 2 = removed)."""
    services = services or {"WKD": WEEKDAYS}
    days = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    calendar: dict[str, Sequence[object]] = {"service_id": list(services)}
    for day in days:
        calendar[day] = [str(flags.get(day, 0)) for flags in services.values()]
    calendar |= {
        "start_date": ["20260901"] * len(services),
        "end_date": ["20261231"] * len(services),
    }
    write(folder / "calendar.parquet", {k: _strings(v) for k, v in calendar.items()})
    write(
        folder / "calendar_dates.parquet",
        {
            "service_id": _strings([e[0] for e in exceptions]),
            "date": _strings([e[1] for e in exceptions]),
            "exception_type": _strings([e[2] for e in exceptions]),
        },
    )
    write(
        folder / "trips.parquet",
        {
            "route_id": _strings([v[0] for v in trips.values()]),
            "service_id": _strings([v[2] if len(v) == 3 else "WKD" for v in trips.values()]),
            "trip_id": _strings(list(trips)),
            "direction_id": _strings([v[1] for v in trips.values()]),
        },
    )
    write(
        folder / "stop_times.parquet",
        {
            "trip_id": _strings([s[0] for s in stop_times]),
            "arrival_time": _strings([s[2] for s in stop_times]),
            "departure_time": _strings([s[2] for s in stop_times]),
            "stop_id": _strings([s[1] for s in stop_times]),
            "stop_sequence": _strings(list(range(len(stop_times)))),  # increasing within a trip
            "timepoint": _strings([s[3] for s in stop_times]),
        },
    )
    write(
        folder / "stops.parquet",
        {
            "stop_id": _strings(list(stops)),
            "stop_lat": pa.array([c[0] for c in stops.values()], pa.float64()),
            "stop_lon": pa.array([c[1] for c in stops.values()], pa.float64()),
        },
    )


def sources() -> tuple[Sources, ScheduleVersion, ScheduleVersion]:
    """One bus and one subway schedule, bus trip updates + vehicle positions, subway updates."""
    lic = "test"
    bus = ScheduleVersion(
        "bus_s", "bus", "bus.zip", "v1:" + "a" * 64, date(2026, 9, 1), date(2026, 12, 31), lic
    )
    sub = ScheduleVersion(
        "sub_s", "subway", "sub.zip", "v1:" + "b" * 64, date(2026, 9, 1), date(2026, 12, 31), lic
    )
    feeds = (
        RealtimeFeed("bus", "trip_updates", "u1", "bus", lic),
        RealtimeFeed("bus", "vehicle_positions", "u2", "bus", lic),
        RealtimeFeed("sub", "trip_updates", "u3", "subway", lic),
    )
    window = DateRange(DAY, DAY)
    return Sources("file:///unused", window, window, feeds, (bus, sub), SCHEDULE_TABLES), bus, sub


def partition(feed_type: str, alias: str, day: date = DAY) -> str:
    return realtime_relpath(feed_type, day, alias)


def schedule_folder(landing: Path, version: ScheduleVersion) -> Path:
    return landing / schedule_dir(version)
