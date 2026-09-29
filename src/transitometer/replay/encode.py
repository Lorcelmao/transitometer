"""Re-encode archived (flattened) GTFS-RT rows into protobuf FeedEntity messages and back.

The gtfsrt.io archive stores each real feed snapshot flattened to Parquet rows that share a
`source_file`. Re-encoding changes the transport encoding only; every field used downstream
must survive the round trip (tests/test_replay_encode.py).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
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
    """Copy non-null row values into message fields; report whether anything was set.

    An empty string is a value, not a null: proto2 fields keep presence, so it round-trips."""
    touched = False
    for column, field in mapping.items():
        value = row.get(column)
        if value is not None:
            setattr(message, field, value)
            touched = True
    return touched


def _deleted(entity: rt.FeedEntity) -> bool | None:
    """The archive keeps is_deleted NULL when the feed did not set it."""
    return entity.is_deleted if entity.HasField("is_deleted") else None


def vehicle_entity(row: Row) -> rt.FeedEntity:
    """Build a FeedEntity carrying a VehiclePosition from one archive row."""
    entity = rt.FeedEntity(id=row["entity_id"])
    if row.get("is_deleted") is not None:
        entity.is_deleted = row["is_deleted"]
    vp = entity.vehicle
    if not _set(vp.trip, _TRIP_FIELDS, row):
        vp.ClearField("trip")
    if not _set(vp.vehicle, _VEHICLE_FIELDS, row):
        vp.ClearField("vehicle")
    if row.get("latitude") is not None and row.get("longitude") is not None:
        _set(vp.position, _POSITION_FIELDS, row)
    for field in _TOP_FIELDS:
        value = row.get(field)
        if value is not None:
            setattr(vp, field, value)
    return entity


def decode_vehicle(payload: bytes) -> dict[str, Any]:
    """Inverse of vehicle_entity (used by tests and debugging): bytes -> archive-shaped dict."""
    entity = rt.FeedEntity.FromString(payload)
    vp = entity.vehicle
    out: dict[str, Any] = {"entity_id": entity.id, "is_deleted": _deleted(entity)}
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


# Trip updates: the archive flattens each FeedEntity into one row per StopTimeUpdate, repeating
# the entity-level columns on every row (an entity without stop updates is one row with every
# stop column null).
_TU_TRIP_FIELDS = {**_TRIP_FIELDS}
_TU_MODIFIED_TRIP = {
    "modified_trip_modifications_id": "modifications_id",
    "modified_trip_affected_trip_id": "affected_trip_id",
    "modified_trip_start_date": "start_date",
    "modified_trip_start_time": "start_time",
}
_TU_VEHICLE_FIELDS = {**_VEHICLE_FIELDS, "wheelchair_accessible": "wheelchair_accessible"}
_TU_TOP_FIELDS = {"trip_timestamp": "timestamp", "trip_delay": "delay"}
_TU_TRIP_PROPERTIES = {
    "trip_properties_trip_id": "trip_id",
    "trip_properties_start_date": "start_date",
    "trip_properties_start_time": "start_time",
    "trip_properties_shape_id": "shape_id",
    "trip_properties_trip_headsign": "trip_headsign",
    "trip_properties_trip_short_name": "trip_short_name",
}
_STU_FIELDS = {
    "stop_sequence": "stop_sequence",
    "stop_id": "stop_id",
    "departure_occupancy_status": "departure_occupancy_status",
    "stop_schedule_relationship": "schedule_relationship",
}
_STU_EVENTS = {
    "arrival": {
        "arrival_delay": "delay",
        "arrival_time": "time",
        "arrival_uncertainty": "uncertainty",
        "arrival_scheduled_time": "scheduled_time",
    },
    "departure": {
        "departure_delay": "delay",
        "departure_time": "time",
        "departure_uncertainty": "uncertainty",
        "departure_scheduled_time": "scheduled_time",
    },
}
_STU_PROPERTIES = {
    "assigned_stop_id": "assigned_stop_id",
    "stop_headsign": "stop_headsign",
    "pickup_type": "pickup_type",
    "drop_off_type": "drop_off_type",
}
ENTITY_COLUMNS = (
    "entity_id",
    "is_deleted",
    *_TU_TRIP_FIELDS,
    *_TU_MODIFIED_TRIP,
    *_TU_VEHICLE_FIELDS,
    *_TU_TOP_FIELDS,
    *_TU_TRIP_PROPERTIES,
)
STOP_COLUMNS = (
    *_STU_FIELDS,
    *(column for event in _STU_EVENTS.values() for column in event),
    *_STU_PROPERTIES,
)
# Archive columns the trip-update replay reads (and nothing else).
TRIP_UPDATE_COLUMNS = ("source_file", "feed_timestamp", *ENTITY_COLUMNS, *STOP_COLUMNS)


def _get(message: Any, mapping: Mapping[str, str], present: bool, out: dict[str, Any]) -> None:
    for column, field in mapping.items():
        out[column] = getattr(message, field) if present and message.HasField(field) else None


def trip_update_entity(rows: Sequence[Row]) -> rt.FeedEntity:
    """Build a FeedEntity carrying a TripUpdate from the archive rows of one entity."""
    first = rows[0]
    entity = rt.FeedEntity(id=first["entity_id"])
    if first.get("is_deleted") is not None:
        entity.is_deleted = first["is_deleted"]
    tu = entity.trip_update
    tu.trip.SetInParent()  # trip is required by the spec: present even when every field is null
    _set(tu.trip, _TU_TRIP_FIELDS, first)
    if not _set(tu.trip.modified_trip, _TU_MODIFIED_TRIP, first):
        tu.trip.ClearField("modified_trip")
    if not _set(tu.vehicle, _TU_VEHICLE_FIELDS, first):
        tu.ClearField("vehicle")
    _set(tu, _TU_TOP_FIELDS, first)
    if not _set(tu.trip_properties, _TU_TRIP_PROPERTIES, first):
        tu.ClearField("trip_properties")
    for row in rows:
        if all(row.get(column) is None for column in STOP_COLUMNS):
            continue  # the placeholder row of an entity without stop updates
        stu = tu.stop_time_update.add()
        _set(stu, _STU_FIELDS, row)
        for event, mapping in _STU_EVENTS.items():
            if not _set(getattr(stu, event), mapping, row):
                stu.ClearField(event)
        if not _set(stu.stop_time_properties, _STU_PROPERTIES, row):
            stu.ClearField("stop_time_properties")
    return entity


def decode_trip_update(payload: bytes) -> list[dict[str, Any]]:
    """Inverse of trip_update_entity: bytes -> the entity's archive-shaped rows."""
    entity = rt.FeedEntity.FromString(payload)
    tu = entity.trip_update
    base: dict[str, Any] = {"entity_id": entity.id, "is_deleted": _deleted(entity)}
    _get(tu.trip, _TU_TRIP_FIELDS, tu.HasField("trip"), base)
    _get(tu.trip.modified_trip, _TU_MODIFIED_TRIP, tu.trip.HasField("modified_trip"), base)
    _get(tu.vehicle, _TU_VEHICLE_FIELDS, tu.HasField("vehicle"), base)
    _get(tu, _TU_TOP_FIELDS, True, base)
    _get(tu.trip_properties, _TU_TRIP_PROPERTIES, tu.HasField("trip_properties"), base)
    if not tu.stop_time_update:
        return [{**base, **dict.fromkeys(STOP_COLUMNS)}]
    rows = []
    for stu in tu.stop_time_update:
        row = dict(base)
        _get(stu, _STU_FIELDS, True, row)
        for event, mapping in _STU_EVENTS.items():
            _get(getattr(stu, event), mapping, stu.HasField(event), row)
        _get(stu.stop_time_properties, _STU_PROPERTIES, stu.HasField("stop_time_properties"), row)
        rows.append(row)
    return rows


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
