"""Run the golden SQL over the landing zone for the golden window and export the results.

Outputs (per window) go to <data root>/golden/<start>_<end>/*.parquet, sorted so re-runs are
byte-identical; a small JSON summary and the output checksums are committed to the repo.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from importlib import resources
from pathlib import Path
from string import Template
from typing import Any

import duckdb

from transitometer.ingest.sources import DateRange, Sources, realtime_relpath, schedule_dir

SQL_STEPS = (
    "01_schedule.sql",
    "02_stop_events.sql",
    "03_matching.sql",
    "04_otp.sql",
    "05_headways.sql",
    "06_crosscheck.sql",
    "07_terminals.sql",
    "08_missing_trips.sql",
    "09_segments.sql",
    "10_scorecards.sql",
    "11_early_warning.sql",
    "12_feed_quality.sql",
)
EXPORTED_TABLES = (
    "stop_events",
    "otp_summary",
    "otp_route_hour",
    "headways",
    "headway_regularity",
    "headway_summary",
    "trip_match_summary",
    "event_status_summary",
    "crosscheck_summary",
    "end_of_trip_summary",
    "multi_unit_summary",
    "ambiguous_summary",
    "stale_summary",
    "delay_sanity_summary",
    "terminal_events",
    "terminal_summary",
    "trip_delivery",
    "missing_trip_summary",
    "missing_by_route",
    "segments",
    "segment_travel_stats",
    "trip_delay_attribution",
    "delay_attribution_summary",
    "route_scorecard",
    "route_hour_scorecard",
    "stop_hour_reliability",
    "warning_decisions",
    "early_warning_summary",
    "position_jumps",
    "feed_quality_metrics",
    "feed_quality_score",
)
SUMMARY_TABLES = (
    "event_status_summary",
    "trip_match_summary",
    "multi_unit_summary",
    "ambiguous_summary",
    "end_of_trip_summary",
    "otp_summary",
    "headway_summary",
    "crosscheck_summary",
    "stale_summary",
    "delay_sanity_summary",
    "terminal_summary",
    "missing_trip_summary",
    "delay_attribution_summary",
    "early_warning_summary",
    "feed_quality_score",
    "feed_quality_metrics",
)


@dataclass(frozen=True)
class Params:
    """Tunable golden rules; every value is recorded in the summary for traceability."""

    timezone: str = "America/New_York"
    max_lead_s: int = 180  # stop-event plausibility: last prediction vs last time listed
    max_stale_s: int = 90  # prediction already this far in the past while listed = echo
    terminal_grace_s: int = 300  # final stop: prediction vs trip's last snapshot
    early_s: int = 60  # OTP band: at most 1 min early ...
    late_s: int = 300  # ... and at most 5 min late
    bunched_ratio: float = 0.25
    gap_ratio: float = 2.0
    regular_tolerance: float = 0.2
    crosscheck_slack_s: int = 60
    terminal_radius_m: int = 50  # a vehicle position this close to the last stop = arrival
    outage_gap_s: int = 300  # snapshot gap that makes overlapping trips 'unknown' for BR3
    partial_share: float = 0.5  # BR3: fewer passed intermediate stops than this share = partial
    bootstrap_resamples: int = 200
    bootstrap_seed: str = "transitometer"
    min_events: int = 10  # scorecard cells with fewer events are flagged insufficient
    min_trips: int = 5  # routes / route-hours with fewer trips (resampling units) likewise
    warn_headway_ratio: float = 0.5  # early warning: headway at most this share of the reference
    warn_trend_weight: float = 0.5  # early warning: weight of the delay trend in the projection


@dataclass
class GoldenResult:
    out_dir: Path
    row_counts: dict[str, int] = field(default_factory=dict)
    checksums: dict[str, str] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)


def _sql_list(paths: list[Path]) -> str:
    return "[" + ", ".join("'" + p.as_posix().replace("'", "''") + "'" for p in paths) + "]"


def _inputs(sources: Sources, landing: Path) -> dict[str, str]:
    """File lists and service days for the golden window, as SQL literals."""
    golden = sources.golden_window
    # Service days spill into the next UTC archive partition (see ingest/sources.py).
    partitions = DateRange(golden.start, golden.end + timedelta(days=1)).days()

    def realtime(group: str, feed_type: str) -> str:
        paths = [
            landing / realtime_relpath(feed.feed_type, day, feed.alias)
            for feed in sources.realtime
            if feed.schedule_group == group and feed.feed_type == feed_type
            for day in partitions
        ]
        if not paths:
            raise ValueError(f"no {group} {feed_type} feed configured")
        return _sql_list(paths)

    def schedule(group: str, table: str) -> str:
        paths = [
            landing / schedule_dir(v) / f"{table}.parquet"
            for v in sources.schedules
            if v.group == group
        ]
        return _sql_list(paths)

    values = {
        "service_dates": "[" + ", ".join(f"'{d:%Y%m%d}'" for d in golden.days()) + "]",
        "bus_tu": realtime("bus", "trip_updates"),
        "bus_vp": realtime("bus", "vehicle_positions"),
        "subway_tu": realtime("subway", "trip_updates"),
    }
    for group in ("bus", "subway"):
        for table in ("calendar", "calendar_dates", "trips", "stop_times", "stops"):
            values[f"{group}_{table}"] = schedule(group, table)
    return values


def render(step: str, values: dict[str, Any]) -> str:
    text = resources.files("transitometer.golden").joinpath("sql").joinpath(step).read_text("utf-8")
    return Template(text).substitute({k: str(v) for k, v in values.items()})


def _rows(con: duckdb.DuckDBPyConnection, table: str) -> list[dict[str, Any]]:
    cursor = con.execute(f"SELECT * FROM {table} ORDER BY ALL")
    columns = [c[0] for c in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def run(
    sources: Sources,
    landing: Path,
    out_root: Path,
    params: Params | None = None,
    memory_limit: str = "14GB",
    threads: int = 8,
    log: Callable[[str], None] = lambda _: None,
) -> GoldenResult:
    params = params or Params()
    golden = sources.golden_window
    out_dir = out_root / f"{golden.start:%Y%m%d}_{golden.end:%Y%m%d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    values: dict[str, Any] = {**_inputs(sources, landing), **vars(params)}
    result = GoldenResult(out_dir=out_dir)

    with duckdb.connect() as con:
        con.execute(f"SET memory_limit = '{memory_limit}'")
        con.execute(f"SET temp_directory = '{(out_root / 'tmp').as_posix()}'")
        # Row order inside intermediate tables is irrelevant (every export is ORDER BY ALL), and
        # preserving it stops large aggregations from spilling; fewer threads bound the number of
        # partial hash tables built in parallel.
        con.execute("SET preserve_insertion_order = false")
        con.execute(f"SET threads = {threads}")
        for number, step in enumerate(SQL_STEPS, start=1):
            log(f"{step} started ({number}/{len(SQL_STEPS)})")
            started = time.perf_counter()
            con.execute(render(step, values))
            log(f"{step} done in {time.perf_counter() - started:.0f}s")
        for table in EXPORTED_TABLES:
            target = out_dir / f"{table}.parquet"
            con.execute(
                f"COPY (SELECT * FROM {table} ORDER BY ALL) TO '{target.as_posix()}' "
                "(FORMAT parquet, COMPRESSION zstd)"
            )
            count = con.execute(f"SELECT count(*) FROM {table}").fetchone()
            result.row_counts[table] = int(count[0]) if count else 0
            result.checksums[target.name] = hashlib.sha256(target.read_bytes()).hexdigest()
        result.summary = {
            "golden_window": {"start": golden.start.isoformat(), "end": golden.end.isoformat()},
            "params": vars(params),
            "row_counts": result.row_counts,
            **{table: _rows(con, table) for table in SUMMARY_TABLES},
        }
    return result


# Kept only in the data folder (together ~90 % of the output); their checksums are committed.
LARGE_TABLES = ("stop_events", "headways", "segments")


def write_repo_artifacts(result: GoldenResult, repo_dir: Path) -> None:
    """Commit-sized outputs: summary numbers, checksums of every Parquet result, and byte copies
    of all but the large tables (golden/tables/)."""
    repo_dir.mkdir(parents=True, exist_ok=True)
    for name, body in (("summary.json", result.summary), ("checksums.json", result.checksums)):
        (repo_dir / name).write_text(
            json.dumps(body, indent=2, default=str) + "\n", encoding="utf-8", newline="\n"
        )
    tables = repo_dir / "tables"
    tables.mkdir(exist_ok=True)
    for stale in tables.glob("*.parquet"):
        stale.unlink()
    for table in EXPORTED_TABLES:
        if table not in LARGE_TABLES:
            shutil.copyfile(result.out_dir / f"{table}.parquet", tables / f"{table}.parquet")
