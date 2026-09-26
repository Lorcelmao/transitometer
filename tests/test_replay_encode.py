from __future__ import annotations

from typing import Any

import pytest

from transitometer.ops.skeleton import project
from transitometer.replay.encode import (
    VEHICLE_COLUMNS,
    decode_vehicle,
    snapshots,
    vehicle_entity,
)
from transitometer.replay.produce import epoch


def _row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {column: None for column in VEHICLE_COLUMNS}
    row.update(
        source_file="vehicle_positions/.../2026-09-22T14:00:18.000Z.pb",
        feed_timestamp=1_790_085_618,
        entity_id="MTA NYCT_8421",
        is_deleted=False,
        trip_id="MQ_D6-Weekday-SDon-084000_M15_401",
        route_id="M15",
        direction_id=1,
        start_date="20260922",
        vehicle_id="MTA NYCT_8421",
        latitude=40.7580,
        longitude=-73.9855,
        bearing=182.5,
        stop_id="401906",
        current_status=2,
        timestamp=1_790_085_600,
    )
    row.update(overrides)
    return row


def _roundtrip(row: dict[str, Any]) -> dict[str, Any]:
    return decode_vehicle(vehicle_entity(row).SerializeToString())


def test_roundtrip_preserves_every_populated_field() -> None:
    row = _row()
    decoded = _roundtrip(row)
    for column, value in row.items():
        if column in ("source_file", "feed_timestamp"):
            continue  # carried in Kafka headers, not the entity
        if isinstance(value, float):
            assert decoded[column] == pytest.approx(value, rel=1e-6)  # protobuf float32
        else:
            assert decoded[column] == value, column


def test_null_and_empty_fields_stay_absent() -> None:
    decoded = _roundtrip(_row(bearing=None, stop_id="", vehicle_id=None, route_id=None))
    assert decoded["bearing"] is None and decoded["stop_id"] is None
    assert decoded["vehicle_id"] is None and decoded["route_id"] is None


def test_position_requires_both_coordinates() -> None:
    entity = vehicle_entity(_row(longitude=None))
    assert not entity.vehicle.HasField("position")


def test_entity_without_trip_or_vehicle_descriptor() -> None:
    blank = {c: None for c in ("trip_id", "route_id", "direction_id", "start_date")}
    entity = vehicle_entity(_row(**blank, vehicle_id=None))
    assert not entity.vehicle.HasField("trip") and not entity.vehicle.HasField("vehicle")


def test_deleted_flag_survives() -> None:
    assert _roundtrip(_row(is_deleted=True))["is_deleted"] is True


def test_snapshots_group_by_file_in_time_order() -> None:
    rows = [
        _row(source_file="b.pb", feed_timestamp=20, entity_id="1"),
        _row(source_file="a.pb", feed_timestamp=10, entity_id="2"),
        _row(source_file="b.pb", feed_timestamp=20, entity_id="3"),
    ]
    groups = list(snapshots(rows))
    assert [(s.source_file, s.feed_timestamp, len(s.rows)) for s in groups] == [
        ("a.pb", 10, 1),
        ("b.pb", 20, 2),
    ]


def test_epoch_requires_explicit_utc_offset() -> None:
    assert epoch("2026-09-22T14:00:00Z") == 1_790_085_600
    with pytest.raises(ValueError):
        epoch("2026-09-22T14:00:00")


def test_projection_scales_measured_parts() -> None:
    parts = project({"image_spark": 10**9, "images_on_disk": 3 * 10**9, "silver_delta_hour": 10**7})
    assert parts["images"] == 3.0
    assert parts["silver_vehicle_positions_7d"] == pytest.approx(1.68)
    assert parts["steady_total"] == pytest.approx(3.0 + 2 + 3 + 1.68 + 5.04 + 1, abs=0.02)
