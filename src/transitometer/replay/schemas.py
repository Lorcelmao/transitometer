"""Canonical record schemas of the replay: what a consumer decodes from each topic.

Decoded rows use the archive's own column names and types, so an engine's decoded stream can be
compared with the archive (and the golden reference) column for column. Kafka headers become the
snapshot columns. Service days are 'YYYYMMDD' strings and stop times are absolute epoch seconds
(times past 24:00 need no special handling in the stream; see golden/sql/01_schedule.sql).
"""

from __future__ import annotations

import pyarrow as pa

SNAPSHOT_FIELDS = [
    pa.field("feed", pa.string(), nullable=False),
    pa.field("source_file", pa.string(), nullable=False),
    pa.field("feed_timestamp", pa.uint64(), nullable=False),
    pa.field("fetch_timestamp_us", pa.int64()),  # the archive misses it on rare snapshots
]

_TRIP = [
    pa.field("trip_id", pa.string()),
    pa.field("route_id", pa.string()),
    pa.field("direction_id", pa.uint32()),
    pa.field("start_time", pa.string()),
    pa.field("start_date", pa.string()),
    pa.field("schedule_relationship", pa.int32()),
]
_MODIFIED_TRIP = [
    pa.field(name, pa.string())
    for name in (
        "modified_trip_modifications_id",
        "modified_trip_affected_trip_id",
        "modified_trip_start_date",
        "modified_trip_start_time",
    )
]

TRIP_UPDATE_ROW = pa.schema(
    [
        *SNAPSHOT_FIELDS,
        pa.field("entity_id", pa.string(), nullable=False),
        pa.field("is_deleted", pa.bool_()),
        *_TRIP,
        *_MODIFIED_TRIP,
        pa.field("vehicle_id", pa.string()),
        pa.field("vehicle_label", pa.string()),
        pa.field("license_plate", pa.string()),
        pa.field("wheelchair_accessible", pa.int32()),
        pa.field("trip_timestamp", pa.uint64()),
        pa.field("trip_delay", pa.int32()),
        *[
            pa.field(name, pa.string())
            for name in (
                "trip_properties_trip_id",
                "trip_properties_start_date",
                "trip_properties_start_time",
                "trip_properties_shape_id",
                "trip_properties_trip_headsign",
                "trip_properties_trip_short_name",
            )
        ],
        pa.field("stop_sequence", pa.uint32()),
        pa.field("stop_id", pa.string()),
        pa.field("departure_occupancy_status", pa.int32()),
        pa.field("stop_schedule_relationship", pa.int32()),
        pa.field("arrival_delay", pa.int32()),
        pa.field("arrival_time", pa.int64()),
        pa.field("arrival_uncertainty", pa.int32()),
        pa.field("arrival_scheduled_time", pa.int64()),
        pa.field("departure_delay", pa.int32()),
        pa.field("departure_time", pa.int64()),
        pa.field("departure_uncertainty", pa.int32()),
        pa.field("departure_scheduled_time", pa.int64()),
        pa.field("assigned_stop_id", pa.string()),
        pa.field("stop_headsign", pa.string()),
        pa.field("pickup_type", pa.int32()),
        pa.field("drop_off_type", pa.int32()),
    ]
)

VEHICLE_ROW = pa.schema(
    [
        *SNAPSHOT_FIELDS,
        pa.field("entity_id", pa.string(), nullable=False),
        pa.field("is_deleted", pa.bool_()),
        *_TRIP,
        pa.field("vehicle_id", pa.string()),
        pa.field("vehicle_label", pa.string()),
        pa.field("license_plate", pa.string()),
        pa.field("latitude", pa.float32()),
        pa.field("longitude", pa.float32()),
        pa.field("bearing", pa.float32()),
        pa.field("odometer", pa.float64()),
        pa.field("speed", pa.float32()),
        pa.field("current_stop_sequence", pa.uint32()),
        pa.field("stop_id", pa.string()),
        pa.field("current_status", pa.int32()),
        pa.field("timestamp", pa.uint64()),
        pa.field("congestion_level", pa.int32()),
        pa.field("occupancy_status", pa.int32()),
        pa.field("occupancy_percentage", pa.uint32()),
    ]
)

SNAPSHOT_MARKER = pa.schema(
    [
        *SNAPSHOT_FIELDS,
        pa.field("entities", pa.int64(), nullable=False),
        pa.field("rows", pa.int64(), nullable=False),
    ]
)
