"""Source specification (config/sources.json) expanded into the concrete files to fetch.

`window` is expressed in New York service days. The archive's `date=` partitions are UTC days,
and a NYC service day (EDT = UTC-4, with trips running past midnight) spills into the next UTC
day, so realtime partitions are fetched from window.start through window.end + 1 day.

Landing layout (relative to <data root>/landing):
  realtime/<feed_type>/date=<YYYY-MM-DD>/feed=<alias>/data.parquet
  schedules/<alias>/<digest>/<table>
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

REALTIME_FEED_TYPES = frozenset({"trip_updates", "vehicle_positions"})


def b64url(text: str) -> str:
    """URL-safe base64 without padding, as used by the gtfsrt.io archive layout."""
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"window end {self.end} is before start {self.start}")

    def days(self) -> list[date]:
        count = (self.end - self.start).days + 1
        return [self.start + timedelta(days=i) for i in range(count)]


@dataclass(frozen=True)
class RealtimeFeed:
    alias: str
    feed_type: str
    feed_url: str
    schedule_group: str
    license: str


@dataclass(frozen=True)
class ScheduleVersion:
    alias: str
    group: str
    feed_url: str
    digest: str
    valid_from: date
    valid_to: date
    license: str


@dataclass(frozen=True)
class FileSpec:
    """One file to download: where it comes from, where it lands, and why."""

    url: str
    relpath: str
    kind: str  # "realtime" | "schedule"
    source: str  # feed alias
    license: str


@dataclass(frozen=True)
class Sources:
    archive_base_url: str
    window: DateRange
    golden_window: DateRange
    realtime: tuple[RealtimeFeed, ...]
    schedules: tuple[ScheduleVersion, ...]
    schedule_tables: tuple[str, ...]

    def realtime_partitions(self) -> list[date]:
        """UTC archive partitions needed to cover the service-day window completely."""
        return DateRange(self.window.start, self.window.end + timedelta(days=1)).days()

    def files(self) -> list[FileSpec]:
        specs: list[FileSpec] = []
        for feed in self.realtime:
            for day in self.realtime_partitions():
                key = f"{feed.feed_type}/date={day.isoformat()}/base64url={b64url(feed.feed_url)}"
                specs.append(
                    FileSpec(
                        url=f"{self.archive_base_url}/{key}/data.parquet",
                        relpath=realtime_relpath(feed.feed_type, day, feed.alias),
                        kind="realtime",
                        source=feed.alias,
                        license=feed.license,
                    )
                )
        for version in self.schedules:
            prefix = f"schedules/base64url={b64url(version.feed_url)}/_feed_digest={version.digest}"
            for table in self.schedule_tables:
                specs.append(
                    FileSpec(
                        url=f"{self.archive_base_url}/{prefix}/{table}",
                        relpath=f"{schedule_dir(version)}/{table}",
                        kind="schedule",
                        source=version.alias,
                        license=version.license,
                    )
                )
        return specs


def realtime_relpath(feed_type: str, day: date, alias: str) -> str:
    return f"realtime/{feed_type}/date={day.isoformat()}/feed={alias}/data.parquet"


def schedule_dir(version: ScheduleVersion) -> str:
    # "v1:<sha256>" -> "v1-<first 16 hex>": short, filesystem-safe, still unambiguous in practice.
    scheme, _, digest = version.digest.partition(":")
    return f"schedules/{version.alias}/{scheme}-{digest[:16]}"


def _range(raw: dict[str, Any]) -> DateRange:
    return DateRange(date.fromisoformat(raw["start"]), date.fromisoformat(raw["end"]))


def load_sources(path: Path) -> Sources:
    raw = json.loads(path.read_text(encoding="utf-8"))
    sources = Sources(
        archive_base_url=raw["archive_base_url"].rstrip("/"),
        window=_range(raw["window"]),
        golden_window=_range(raw["golden_window"]),
        realtime=tuple(RealtimeFeed(**feed) for feed in raw["realtime"]),
        schedules=tuple(
            ScheduleVersion(
                alias=s["alias"],
                group=s["group"],
                feed_url=s["feed_url"],
                digest=s["digest"],
                valid_from=date.fromisoformat(s["valid_from"]),
                valid_to=date.fromisoformat(s["valid_to"]),
                license=s["license"],
            )
            for s in raw["schedules"]
        ),
        schedule_tables=tuple(raw["schedule_tables"]),
    )
    _check(sources)
    return sources


def _check(sources: Sources) -> None:
    w, g = sources.window, sources.golden_window
    if not (w.start <= g.start and g.end <= w.end):
        raise ValueError("golden_window must lie inside window")
    groups = {s.group for s in sources.schedules}
    for feed in sources.realtime:
        if feed.feed_type not in REALTIME_FEED_TYPES:
            raise ValueError(f"{feed.alias}: unknown feed_type {feed.feed_type!r}")
        if feed.schedule_group not in groups:
            raise ValueError(f"{feed.alias}: no schedule for group {feed.schedule_group!r}")
    for version in sources.schedules:
        if version.valid_from > w.start or version.valid_to < w.end:
            raise ValueError(f"schedule {version.alias} does not cover the whole window")
