"""Validate the landing zone and measure its volume (IMPLEMENTATION_PLAN.md S1 tests).

Hard failures: missing or truncated files, missing required columns, window days with no
active scheduled service. Warnings: weak real-time <-> schedule trip_id matching (the schedule
join every BR depends on) and long gaps between feed snapshots.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pyarrow.parquet as pq

from transitometer.ingest.fetch import ManifestEntry
from transitometer.ingest.sources import (
    DateRange,
    ScheduleVersion,
    Sources,
    realtime_relpath,
    schedule_dir,
)

REQUIRED_COLUMNS: dict[str, frozenset[str]] = {
    "trip_updates": frozenset(
        {
            "source_file",
            "feed_timestamp",
            "entity_id",
            "trip_id",
            "route_id",
            "start_date",
            "stop_sequence",
            "stop_id",
            "arrival_time",
            "departure_time",
        }
    ),
    "vehicle_positions": frozenset(
        {
            "source_file",
            "feed_timestamp",
            "entity_id",
            "trip_id",
            "route_id",
            "vehicle_id",
            "latitude",
            "longitude",
            "timestamp",
            "current_status",
            "stop_id",
        }
    ),
}
MIN_TRIP_MATCH = 0.9
MAX_SNAPSHOT_GAP_MIN = 15.0


@dataclass
class Report:
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    realtime_days: list[dict[str, Any]] = field(default_factory=list)
    service_coverage: dict[str, dict[str, int]] = field(default_factory=dict)
    trip_matching: list[dict[str, Any]] = field(default_factory=list)
    totals: dict[str, float] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.failures


def _sql_path(path: Path) -> str:
    return path.as_posix().replace("'", "''")


def check_files(
    sources: Sources, landing: Path, manifest: dict[str, ManifestEntry], report: Report
) -> None:
    """Every expected file exists with the manifest's byte size (full SHA check is fetch's job)."""
    for spec in sources.files():
        entry = manifest.get(spec.relpath)
        path = landing / spec.relpath
        if entry is None:
            report.failures.append(f"not in manifest: {spec.relpath}")
        elif not path.exists():
            report.failures.append(f"missing file: {spec.relpath}")
        elif path.stat().st_size != entry.bytes:
            report.failures.append(f"size mismatch: {spec.relpath}")


def check_realtime(
    sources: Sources, landing: Path, con: duckdb.DuckDBPyConnection, report: Report
) -> None:
    """Schema, rows, snapshots and the longest snapshot gap, per feed and UTC partition."""
    total_bytes = total_rows = 0
    for feed in sources.realtime:
        for day in sources.realtime_partitions():
            path = landing / realtime_relpath(feed.feed_type, day, feed.alias)
            if not path.exists():
                continue
            missing = REQUIRED_COLUMNS[feed.feed_type] - set(pq.read_schema(path).names)
            if missing:
                report.failures.append(f"{path.name} {feed.alias} {day}: missing {sorted(missing)}")
                continue
            snapshots, max_gap_min = con.execute(
                f"""
                WITH s AS (
                  SELECT DISTINCT feed_timestamp AS ts FROM read_parquet('{_sql_path(path)}')
                )
                SELECT count(*), max(gap) / 60.0
                FROM (SELECT ts - lag(ts) OVER (ORDER BY ts) AS gap FROM s)
                """
            ).fetchone() or (0, None)
            rows = pq.ParquetFile(path).metadata.num_rows
            size = path.stat().st_size
            total_bytes += size
            total_rows += rows
            report.realtime_days.append(
                {
                    "feed": feed.alias,
                    "feed_type": feed.feed_type,
                    "utc_partition": day.isoformat(),
                    "rows": rows,
                    "bytes": size,
                    "snapshots": snapshots,
                    "max_snapshot_gap_min": None if max_gap_min is None else round(max_gap_min, 1),
                }
            )
            if max_gap_min is not None and max_gap_min > MAX_SNAPSHOT_GAP_MIN:
                report.warnings.append(
                    f"{feed.alias}/{feed.feed_type} {day}: snapshot gap {max_gap_min:.0f} min"
                )
    report.totals = {"realtime_gb": round(total_bytes / 1e9, 2), "realtime_rows": total_rows}


def _schedule_view(landing: Path, versions: list[ScheduleVersion], table: str) -> str:
    paths = [_sql_path(landing / schedule_dir(v) / f"{table}.parquet") for v in versions]
    return "read_parquet([" + ", ".join(f"'{p}'" for p in paths) + "], union_by_name=true)"


def check_service_coverage(
    sources: Sources, landing: Path, con: duckdb.DuckDBPyConnection, report: Report
) -> None:
    """Every schedule version must run service on every window day (calendar + calendar_dates),
    and its own feed_info validity range must cover the window (guards hand-typed config)."""
    weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    first = sources.window.start.strftime("%Y%m%d")
    last = sources.window.end.strftime("%Y%m%d")
    for version in sources.schedules:
        feed_start = feed_end = None
        if (landing / schedule_dir(version) / "feed_info.parquet").exists():  # optional in GTFS
            info = _schedule_view(landing, [version], "feed_info")
            feed_start, feed_end = con.execute(
                "SELECT min(CAST(feed_start_date AS VARCHAR)), max(CAST(feed_end_date AS VARCHAR))"
                f" FROM {info}"
            ).fetchone() or (None, None)
        if feed_start and feed_end and not (feed_start <= first and last <= feed_end):
            report.failures.append(
                f"schedule {version.alias}: feed_info {feed_start}-{feed_end} misses the window"
            )
        cal = _schedule_view(landing, [version], "calendar")
        exc = _schedule_view(landing, [version], "calendar_dates")
        coverage: dict[str, int] = {}
        for day in sources.window.days():
            ymd = day.strftime("%Y%m%d")
            dow = weekdays[day.weekday()]
            (count,) = con.execute(
                f"""
                SELECT count(DISTINCT service_id) FROM (
                  (SELECT service_id FROM {cal}
                   WHERE CAST(start_date AS VARCHAR) <= '{ymd}'
                     AND CAST(end_date AS VARCHAR) >= '{ymd}'
                     AND CAST({dow} AS INTEGER) = 1
                   UNION
                   SELECT service_id FROM {exc}
                   WHERE CAST(date AS VARCHAR) = '{ymd}' AND CAST(exception_type AS INTEGER) = 1)
                  EXCEPT
                  SELECT service_id FROM {exc}
                  WHERE CAST(date AS VARCHAR) = '{ymd}' AND CAST(exception_type AS INTEGER) = 2
                )
                """
            ).fetchone() or (0,)
            coverage[day.isoformat()] = int(count)
            if count == 0:
                report.failures.append(f"schedule {version.alias}: no active service on {day}")
        report.service_coverage[version.alias] = coverage


def _route_direction_key(column: str) -> str:
    """SQL for "083250_1..S03R" -> "083250_1..S": origin time, route and direction letter."""
    return f"split_part({column}, '..', 1) || '..' || left(split_part({column}, '..', 2), 1)"


def check_trip_matching(
    sources: Sources, landing: Path, con: duckdb.DuckDBPyConnection, report: Report
) -> None:
    """Share of real-time trip_ids (golden service days) found in the schedule, by tier.

    Tiers, measured with equality joins; a trip counts as matched if ANY tier matches it:
      exact            real-time trip_id == static trip_id (MTA Bus)
      suffix           == static trip_id after its first "_" (NYCT subway, e.g. static
                       "AFA23GEN-1038-Weekday-00_083250_1..S03R" vs real-time "083250_1..S03R")
      route_direction  origin time + route + direction ("083250_1..S"): real-time ids with no or
                       a different path code after the direction letter (7 line, reroutes)
    Unmatched trips are real added/unscheduled service; how to treat them is decided with the
    golden KPI rules, not here.
    """
    # Service days spill into the next UTC partition (see sources.py).
    golden = DateRange(sources.golden_window.start, sources.golden_window.end + timedelta(days=1))
    for feed in sources.realtime:
        paths = [
            _sql_path(landing / realtime_relpath(feed.feed_type, day, feed.alias))
            for day in golden.days()
        ]
        if not all(Path(p).exists() for p in paths):
            continue
        rt = "read_parquet([" + ", ".join(f"'{p}'" for p in paths) + "])"
        versions = [v for v in sources.schedules if v.group == feed.schedule_group]
        trips = _schedule_view(landing, versions, "trips")
        rt_key = _route_direction_key("trip_id")
        total, exact, suffix, direction, matched = con.execute(
            f"""
            WITH r AS (SELECT DISTINCT trip_id FROM {rt}
                       WHERE trip_id IS NOT NULL AND trip_id <> ''),
                 s AS (SELECT DISTINCT CAST(trip_id AS VARCHAR) AS trip_id FROM {trips}),
                 s_suffix AS (SELECT DISTINCT substr(trip_id, strpos(trip_id, '_') + 1) AS trip_id
                              FROM s WHERE strpos(trip_id, '_') > 0),
                 s_dir AS (SELECT DISTINCT {rt_key} AS k FROM s_suffix
                           WHERE strpos(trip_id, '..') > 0)
            SELECT
              (SELECT count(*) FROM r),
              (SELECT count(*) FROM r SEMI JOIN s USING (trip_id)),
              (SELECT count(*) FROM r SEMI JOIN s_suffix USING (trip_id)),
              (SELECT count(*) FROM r
               WHERE strpos(trip_id, '..') > 0 AND {rt_key} IN (SELECT k FROM s_dir)),
              (SELECT count(*) FROM r
               WHERE trip_id IN (SELECT trip_id FROM s)
                  OR trip_id IN (SELECT trip_id FROM s_suffix)
                  OR (strpos(trip_id, '..') > 0 AND {rt_key} IN (SELECT k FROM s_dir)))
            """
        ).fetchone() or (0, 0, 0, 0, 0)
        ratio = matched / total if total else 0.0
        report.trip_matching.append(
            {
                "feed": feed.alias,
                "feed_type": feed.feed_type,
                "golden_trip_ids": total,
                "exact_match": exact,
                "suffix_match": suffix,
                "route_direction_match": direction,
                "matched_any_tier": matched,
                "match_ratio": round(ratio, 4),
            }
        )
        if ratio < MIN_TRIP_MATCH:
            report.warnings.append(
                f"{feed.alias}/{feed.feed_type}: only {ratio:.1%} of trip_ids match the schedule"
            )


def validate(sources: Sources, landing: Path, manifest: dict[str, ManifestEntry]) -> Report:
    report = Report()
    check_files(sources, landing, manifest, report)
    if report.failures:
        return report
    with duckdb.connect() as con:
        check_realtime(sources, landing, con, report)
        check_service_coverage(sources, landing, con, report)
        check_trip_matching(sources, landing, con, report)
    return report


def summary(report: Report, window: tuple[date, date]) -> dict[str, Any]:
    return {
        "window": {"start": window[0].isoformat(), "end": window[1].isoformat()},
        "ok": report.ok,
        "failures": report.failures,
        "warnings": report.warnings,
        "totals": report.totals,
        "realtime_days": report.realtime_days,
        "service_coverage": report.service_coverage,
        "trip_matching": report.trip_matching,
    }
