"""Raw evidence for a seeded sample of golden stop events, for manual verification.

For each sampled event it shows, straight from the landing Parquet (no golden SQL involved):
the last snapshots that still listed the stop, the first later snapshot of the trip without
it, the scheduled arrival, and (bus) the vehicle-position next-stop trace around it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

from transitometer.golden.runner import _inputs
from transitometer.ingest.sources import Sources


def sample_events(golden_dir: Path, per_group: int, seed: float) -> list[dict[str, Any]]:
    with duckdb.connect() as con:
        con.execute(f"SELECT setseed({seed})")
        cursor = con.execute(
            f"""
            SELECT * FROM (
                SELECT *, row_number() OVER (PARTITION BY grp ORDER BY random()) AS pick
                FROM read_parquet('{(golden_dir / "stop_events.parquet").as_posix()}')
                WHERE status = 'passed'
            ) WHERE pick <= {per_group} ORDER BY grp, pick
            """
        )
        columns = [c[0] for c in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def evidence(sources: Sources, landing: Path, event: dict[str, Any]) -> dict[str, Any]:
    files = _inputs(sources, landing)
    tu = files["bus_tu"] if event["grp"] == "bus" else files["subway_tu"]
    trip, day, stop = event["trip_id"], event["service_date"], event["stop_id"]
    with duckdb.connect() as con:
        snaps = con.execute(
            f"""
            SELECT feed_timestamp,
                   max(CASE WHEN stop_id = ? THEN coalesce(arrival_time, departure_time) END)
                       AS predicted_for_stop,
                   bool_or(stop_id = ?) AS lists_stop
            FROM read_parquet({tu})
            WHERE trip_id = ? AND start_date = ?
            GROUP BY feed_timestamp ORDER BY feed_timestamp
            """,
            [stop, stop, trip, day],
        ).fetchall()
        vp: list[tuple[Any, ...]] = []
        if event["grp"] == "bus":
            vp = con.execute(
                f"""
                SELECT DISTINCT coalesce(timestamp, feed_timestamp) AS ts, stop_id
                FROM read_parquet({files["bus_vp"]})
                WHERE trip_id = ? AND start_date = ?
                ORDER BY ts
                """,
                [trip, day],
            ).fetchall()
    listed = [s for s in snaps if s[2]]
    last_listed = listed[-1][0] if listed else None
    after = [s[0] for s in snaps if last_listed is not None and s[0] > last_listed]
    near_vp = [
        (ts, s)
        for ts, s in vp
        if last_listed is not None and abs(int(ts) - int(last_listed)) <= 300
    ]
    return {
        "event": {
            k: event[k]
            for k in (
                "grp",
                "service_date",
                "trip_id",
                "stop_id",
                "sched_arrival",
                "observed_arrival",
                "delay_s",
                "tier",
            )
        },
        "last_two_listing_snapshots": [(s[0], s[1]) for s in listed[-2:]],
        "first_snapshot_without_stop": after[0] if after else None,
        "trip_snapshots_total": len(snaps),
        "vp_trace_near_dropout": near_vp,
    }
