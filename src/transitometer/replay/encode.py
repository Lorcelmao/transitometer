"""Re-encode archived (flattened) GTFS-RT rows into protobuf FeedEntity messages and back.

The gtfsrt.io archive stores each real feed snapshot flattened to Parquet rows that share a
`source_file`. Re-encoding changes the transport encoding only; every field used downstream
must survive the round trip (tests/test_replay_encode.py).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from google.transit import gtfs_realtime_pb2 as rt

Row = Mapping[str, Any]

# Archive column -> field inside VehiclePosition.trip / .vehicle / .position.
_TRIP_FIELDS = {
    "trip_id": "trip_id",
    "route_id": "route_id",
    "direction_id": "direction_id",
    "start_time": "start_time",
    "start_date": "start_date",
    "schedule_relationship": "schedule_relationship",
}
_VEHICLE_FIELDS = {"vehicle_id": "id", "vehicle_label": "label", "license_plate": "license_plate"}
_POSITION_FIELDS = {
    "latitude": "latitude",
    "longitude": "longitude",
    "bearing": "bearing",
    "odometer": "odometer",
    "speed": "speed",
}
_TOP_FIELDS = (
    "current_stop_sequence",
    "stop_id",
    "current_status",
    "timestamp",
    "congestion_level",
    "occupancy_status",
    "occupancy_percentage",
)

# Archive columns the vehicle-position replay reads (and nothing else).
VEHICLE_COLUMNS = (
    "source_file",
    "feed_timestamp",
    "entity_id",
    "is_deleted",
    *_TRIP_FIELDS,
    *_VEHICLE_FIELDS,
    *_POSITION_FIELDS,
    *_TOP_FIELDS,
)


@dataclass(frozen=True)
class Snapshot:
    """One real feed snapshot: every entity the feed published at one fetch."""

    source_file: str
    feed_timestamp: int
    rows: list[dict[str, Any]]


def _set(message: Any, mapping: Mapping[str, str], row: Row) -> bool:
    """Copy non-null row values into message fields; report whether anything was set."""
    touched = False
    for column, field in mapping.items():
        value = row.get(column)
        if value is not None and value != "":
            setattr(message, field, value)
            touched = True
    return touched


def vehicle_entity(row: Row) -> rt.FeedEntity:
    """Build a FeedEntity carrying a VehiclePosition from one archive row."""
    entity = rt.FeedEntity(id=row["entity_id"])
    if row.get("is_deleted"):
        entity.is_deleted = True
    vp = entity.vehicle
    if not _set(vp.trip, _TRIP_FIELDS, row):
        vp.ClearField("trip")
    if not _set(vp.vehicle, _VEHICLE_FIELDS, row):
        vp.ClearField("vehicle")
    if row.get("latitude") is not None and row.get("longitude") is not None:
        _set(vp.position, _POSITION_FIELDS, row)
    for field in _TOP_FIELDS:
        value = row.get(field)
        if value is not None and value != "":
            setattr(vp, field, value)
    return entity


def decode_vehicle(payload: bytes) -> dict[str, Any]:
    """Inverse of vehicle_entity (used by tests and debugging): bytes -> archive-shaped dict."""
    entity = rt.FeedEntity.FromString(payload)
    vp = entity.vehicle
    out: dict[str, Any] = {"entity_id": entity.id, "is_deleted": entity.is_deleted}
    groups = (
        (vp.trip, _TRIP_FIELDS, vp.HasField("trip")),
        (vp.vehicle, _VEHICLE_FIELDS, vp.HasField("vehicle")),
        (vp.position, _POSITION_FIELDS, vp.HasField("position")),
    )
    for message, mapping, present in groups:
        for column, field in mapping.items():
            out[column] = getattr(message, field) if present and message.HasField(field) else None
    for field in _TOP_FIELDS:
        out[field] = getattr(vp, field) if vp.HasField(field) else None
    return out


def snapshots(rows: list[dict[str, Any]]) -> Iterator[Snapshot]:
    """Group archive rows into snapshots, ordered by feed timestamp then file name."""
    groups: dict[str, list[dict[str, Any]]] = {}
    stamps: dict[str, int] = {}
    for row in rows:
        key = row["source_file"]
        groups.setdefault(key, []).append(row)
        stamps[key] = int(row["feed_timestamp"])
    for key in sorted(groups, key=lambda k: (stamps[k], k)):
        yield Snapshot(source_file=key, feed_timestamp=stamps[key], rows=groups[key])
