"""W2 headway rule as a pure state step, shared by the Spark and Flink arms.

Per key (grp, service_date, route_id, stop_id) an engine keeps the last released passage and a
buffer of passages its watermark has not passed yet. `release` emits, in (observed_arrival,
trip_key) order, every buffered passage strictly older than the watermark: once the watermark
is past t, no passage at or before t can still arrive, so the order of released passages is final.

The headway rule is golden/sql/05_headways.sql: each passage forms a headway with the one before
it; the headway is dropped (but the chain continues) when there is no positive scheduled
reference or when both passages belong to the same vehicle. A passage older than the last released
one arrived too late to be ordered; it is counted and skipped without touching the chain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

BUNCHED_RATIO = 0.25
GAP_RATIO = 2.0
REGULAR_TOLERANCE = 0.2

Passage = dict[str, Any]


@dataclass
class HeadwayState:
    last: Passage | None = None
    buffer: list[Passage] = field(default_factory=list)
    late: int = 0


def classify(headway_s: int, ref_headway_s: float) -> str:
    if headway_s <= BUNCHED_RATIO * ref_headway_s:
        return "bunched"
    if headway_s >= GAP_RATIO * ref_headway_s:
        return "gap"
    if abs(headway_s / ref_headway_s - 1) <= REGULAR_TOLERANCE:
        return "regular"
    return "irregular"


def _order(p: Passage) -> tuple[int, str]:
    return int(p["observed_arrival"]), str(p["trip_key"])


def add(state: HeadwayState, passages: list[Passage]) -> None:
    """Buffer new passages; one older than the last released passage is late and skipped."""
    for p in passages:
        if state.last is not None and _order(p) < _order(state.last):
            state.late += 1
        else:
            state.buffer.append(p)


def release(state: HeadwayState, watermark_s: float) -> list[Passage]:
    """Headway rows for every buffered passage strictly before the watermark, in order."""
    ready = sorted((p for p in state.buffer if p["observed_arrival"] < watermark_s), key=_order)
    if not ready:
        return []
    state.buffer = [p for p in state.buffer if p["observed_arrival"] >= watermark_s]
    rows = []
    for p in ready:
        prev = state.last
        state.last = p
        if prev is None:
            continue
        ref = p.get("ref_headway_s")
        if ref is None or ref <= 0 or p["unit"] == prev["unit"]:
            continue
        headway = int(p["observed_arrival"]) - int(prev["observed_arrival"])
        rows.append(
            {
                "grp": p["grp"],
                "service_date": p["service_date"],
                "route_id": p["route_id"],
                "stop_id": p["stop_id"],
                "service_hour": p["service_hour"],
                "trip_key": p["trip_key"],
                "trip_id": p["trip_id"],
                "unit": p["unit"],
                "source": p["source"],
                "observed_arrival": p["observed_arrival"],
                "prev_trip_key": prev["trip_key"],
                "prev_source": prev["source"],
                "headway_s": headway,
                "ref_headway_s": float(ref),
                "headway_class": classify(headway, float(ref)),
            }
        )
    return rows


def earliest(state: HeadwayState) -> int | None:
    """Event time of the oldest buffered passage (for the engine's event-time timer)."""
    return min((int(p["observed_arrival"]) for p in state.buffer), default=None)


OUTPUT_FIELDS = (
    "grp",
    "service_date",
    "route_id",
    "stop_id",
    "service_hour",
    "trip_key",
    "trip_id",
    "unit",
    "source",
    "observed_arrival",
    "prev_trip_key",
    "prev_source",
    "headway_s",
    "ref_headway_s",
    "headway_class",
)
