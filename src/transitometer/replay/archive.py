"""Read archived feed snapshots and turn each into its Kafka messages.

The gtfsrt.io archive stores one Parquet row group per feed snapshot, rows in feed order, so a
snapshot is read by row-group index and a worker process can encode it on its own. Within a
snapshot, the rows of one FeedEntity are contiguous. Entity ids are not unique per snapshot
(an MTA Bus trip served by two vehicles is two entities with the trip id as entity id), so an
entity is a contiguous run of rows, not a group by id: a new entity starts wherever any
entity-level column changes, or the stop sequence stops increasing (two adjacent entities that
agree on every entity-level column would otherwise merge; none occur on the measured days).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from transitometer.replay.encode import (
    ENTITY_COLUMNS,
    TRIP_UPDATE_COLUMNS,
    VEHICLE_COLUMNS,
    trip_update_entity,
    vehicle_entity,
)


@dataclass(frozen=True)
class Feed:
    """One replayed feed: archive location, entity kind and Kafka topic suffix."""

    name: str  # e.g. "trip_updates.bus"
    kind: str  # "trip_updates" | "vehicle_positions"
    alias: str  # archive partition alias, e.g. "mta_bus"


FEEDS = (
    Feed("trip_updates.bus", "trip_updates", "mta_bus"),
    Feed("trip_updates.subway", "trip_updates", "nyct_subway_1234567s"),
    Feed("vehicle_positions.bus", "vehicle_positions", "mta_bus"),
)


@dataclass(frozen=True)
class EncodedSnapshot:
    """One archive snapshot as Kafka messages, in feed order."""

    path: str  # archive file and row group it came from
    row_group: int
    source_file: str
    feed_timestamp: int
    fetch_timestamp_us: int | None  # None: the archive did not record the fetch (it happens)
    rows: int
    messages: list[tuple[bytes, bytes]]  # (key, protobuf FeedEntity)


def columns(kind: str) -> list[str]:
    entity = TRIP_UPDATE_COLUMNS if kind == "trip_updates" else VEHICLE_COLUMNS
    return [*dict.fromkeys(("source_file", "feed_timestamp", "fetch_timestamp", *entity))]


RUN_COLUMNS = [*ENTITY_COLUMNS, "stop_sequence"]  # what entity boundaries are decided from


def entity_starts(table: pa.Table) -> pa.Array:
    """Boolean per row: does a new trip-update entity start here? (vectorised)"""
    n = table.num_rows
    if n == 0:
        return pa.array([], pa.bool_())
    change = pa.array([False] * (n - 1), pa.bool_())
    for name in ENTITY_COLUMNS:
        column = table[name].combine_chunks()
        if pa.types.is_null(column.type):  # no values at all: never differs
            continue
        a, b = column.slice(1), column.slice(0, n - 1)
        differs = pc.fill_null(pc.not_equal(a, b), False)
        null_flip = pc.not_equal(pc.is_null(a), pc.is_null(b))
        change = pc.or_(change, pc.or_(differs, null_flip))
    sequence = table["stop_sequence"].combine_chunks()
    if not pa.types.is_null(sequence.type):
        restart = pc.fill_null(pc.less_equal(sequence.slice(1), sequence.slice(0, n - 1)), False)
        change = pc.or_(change, restart)
    return pa.concat_arrays([pa.array([True]), change])


def _entity_runs(table: pa.Table) -> list[tuple[int, int]]:
    """[start, end) row ranges of the snapshot's trip-update entities."""
    if table.num_rows == 0:
        return []
    starts = pc.indices_nonzero(entity_starts(table)).to_pylist()
    return list(zip(starts, [*starts[1:], table.num_rows], strict=True))


_OPEN: dict[str, pq.ParquetFile] = {}


def _archive(path: str) -> pq.ParquetFile:
    """Open archive files once per process: their footers describe thousands of row groups."""
    if path not in _OPEN:
        _OPEN[path] = pq.ParquetFile(path)
    return _OPEN[path]


def encode_snapshot(path: str, kind: str, row_group: int) -> EncodedSnapshot:
    """Read one snapshot (row group) and encode each of its entities."""
    table = _archive(path).read_row_group(row_group, columns=columns(kind))
    files = pc.unique(table["source_file"]).to_pylist()
    if len(files) != 1:
        raise ValueError(f"{path} row group {row_group} holds {len(files)} snapshots, expected 1")
    fetch = table["fetch_timestamp"].cast(pa.timestamp("us", tz="UTC")).cast(pa.int64())
    stamps = pc.unique(table["feed_timestamp"]).to_pylist()
    if len(stamps) != 1:
        raise ValueError(f"{path} row group {row_group}: {len(stamps)} feed timestamps")
    body = table.drop_columns(["source_file", "feed_timestamp", "fetch_timestamp"])
    rows: list[dict[str, Any]] = body.to_pylist()
    messages = []
    if kind == "trip_updates":
        for start, end in _entity_runs(table):
            run = rows[start:end]
            key = run[0]["trip_id"] or run[0]["entity_id"]
            messages.append((key.encode(), trip_update_entity(run).SerializeToString()))
    else:
        for row in rows:
            key = row.get("vehicle_id") or row["entity_id"]
            messages.append((key.encode(), vehicle_entity(row).SerializeToString()))
    return EncodedSnapshot(
        path=path,
        row_group=row_group,
        source_file=files[0],
        feed_timestamp=int(stamps[0]),
        fetch_timestamp_us=None if (fetched := pc.max(fetch).as_py()) is None else int(fetched),
        rows=table.num_rows,
        messages=messages,
    )


def row_groups(path: Path, until: int | None = None) -> list[int]:
    """Row groups (snapshots) of the file, optionally only those before `until` (epoch s),
    decided from the row-group statistics without reading data."""
    meta = pq.ParquetFile(path).metadata
    if until is None:
        return list(range(meta.num_row_groups))
    column = meta.schema.to_arrow_schema().get_field_index("feed_timestamp")
    kept = []
    for group in range(meta.num_row_groups):
        stats = meta.row_group(group).column(column).statistics
        if stats is None or not stats.has_min_max:
            raise ValueError(f"{path}: row group {group} has no feed_timestamp statistics")
        if int(stats.min) < until:
            kept.append(group)
    return kept


def entity_counts(path: Path, kind: str, until: int | None = None) -> dict[str, int]:
    """Independent count of the messages a replay must produce, per snapshot (source_file).

    Counted from the archive without encoding anything, one row group at a time (a day holds
    ~175 M trip-update rows): trip updates count entity starts (same boundary rule as the
    encoder), vehicle positions count rows. It proves the pipeline dropped, duplicated or
    re-grouped nothing. `until` limits it like the replay."""
    archive = pq.ParquetFile(path)
    counts: dict[str, int] = {}
    wanted = ["source_file", *(RUN_COLUMNS if kind == "trip_updates" else [])]
    for group in row_groups(path, until):
        table = archive.read_row_group(group, columns=wanted)
        files = table["source_file"].cast(pa.string())
        if kind == "trip_updates" and table.num_rows:
            files = pc.filter(files, entity_starts(table))
        for item in pc.value_counts(files).to_pylist():
            name = str(item["values"])
            counts[name] = counts.get(name, 0) + int(item["counts"])
    return counts
