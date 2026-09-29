"""Replay harness: trip-update fidelity, snapshot encoding, schemas, faults, topic guard, pacing."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from transitometer.replay import faults as faults_mod
from transitometer.replay.archive import FEEDS, EncodedSnapshot, encode_snapshot, entity_counts
from transitometer.replay.encode import (
    STOP_COLUMNS,
    TRIP_UPDATE_COLUMNS,
    decode_trip_update,
    decode_vehicle,
    trip_update_entity,
)
from transitometer.replay.run import (
    Pacer,
    check_topic_prefix,
    encoded_snapshots,
    marker_topic,
    replay_feed,
)
from transitometer.replay.schemas import SNAPSHOT_FIELDS, TRIP_UPDATE_ROW, VEHICLE_ROW
from transitometer.replay.verify import (
    archive_entities,
    decoded_entities,
    murmur2,
    partition_for,
    uncarried_columns,
)

ENTITY_COLUMNS = [c for c in TRIP_UPDATE_COLUMNS if c not in ("source_file", "feed_timestamp")]


def _tu_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = dict.fromkeys(ENTITY_COLUMNS)
    row.update(
        entity_id="MQ_D6-Weekday-SDon-084000_M15_401",
        trip_id="MQ_D6-Weekday-SDon-084000_M15_401",
        route_id="M15",
        direction_id=1,
        start_time="",  # the archive stores an empty string, not NULL
        start_date="20260922",
        schedule_relationship=0,
        vehicle_id="MTA NYCT_8421",
        vehicle_label="",
        trip_timestamp=1_790_085_600,
        trip_delay=-42,
        stop_sequence=7,
        stop_id="401906",
        arrival_time=1_790_085_700,
        departure_time=1_790_085_710,
    )
    row.update(overrides)
    return row


def _roundtrip(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return decode_trip_update(trip_update_entity(rows).SerializeToString())


def test_bus_trip_update_roundtrips_exactly() -> None:
    rows = [
        _tu_row(stop_sequence=i, stop_id=f"S{i}", arrival_time=1_790_085_700 + i) for i in range(5)
    ]
    assert _roundtrip(rows) == rows


def test_every_optional_field_roundtrips() -> None:
    full = _tu_row(
        is_deleted=False,
        modified_trip_modifications_id="mod-1",
        modified_trip_affected_trip_id="T0",
        modified_trip_start_date="20260922",
        modified_trip_start_time="08:00:00",
        license_plate="ABC123",
        wheelchair_accessible=1,
        trip_properties_trip_id="T9",
        trip_properties_start_date="20260922",
        trip_properties_start_time="08:10:00",
        trip_properties_shape_id="SH1",
        trip_properties_trip_headsign="Downtown",
        trip_properties_trip_short_name="15",
        arrival_delay=30,
        arrival_uncertainty=10,
        arrival_scheduled_time=1_790_085_670,
        departure_delay=31,
        departure_uncertainty=11,
        departure_scheduled_time=1_790_085_680,
        departure_occupancy_status=2,
        stop_schedule_relationship=0,
        assigned_stop_id="401907",
        stop_headsign="South Ferry",
        pickup_type=0,
        drop_off_type=1,
    )
    assert all(full[c] is not None for c in ENTITY_COLUMNS if c != "is_deleted")
    assert _roundtrip([full]) == [full]


def test_subway_entity_without_vehicle_or_sequence_roundtrips() -> None:
    rows = [
        _tu_row(
            entity_id="000003",
            trip_id="048000_1..S03R",
            route_id="1",
            direction_id=None,
            vehicle_id=None,
            vehicle_label=None,
            trip_timestamp=None,
            trip_delay=None,
            stop_sequence=None,
            stop_id=stop,
            arrival_time=t,
            departure_time=None,
        )
        for stop, t in (("101S", 1_790_085_700), ("102S", None))
    ]
    assert _roundtrip(rows) == rows


def test_entity_without_stop_updates_is_one_placeholder_row() -> None:
    row = _tu_row(**dict.fromkeys(STOP_COLUMNS))
    entity = trip_update_entity([row])
    assert len(entity.trip_update.stop_time_update) == 0
    assert decode_trip_update(entity.SerializeToString()) == [row]


def _archive(path: Path, snapshots: list[tuple[str, int, list[dict[str, Any]]]]) -> Path:
    """A trip-update archive file with one row group per snapshot, like the real archive."""
    schema = pa.schema(
        [f for f in TRIP_UPDATE_ROW if f.name not in ("feed", "fetch_timestamp_us")]
        + [pa.field("fetch_timestamp", pa.timestamp("us", tz="UTC"))]
    )
    with pq.ParquetWriter(path, schema) as writer:
        for source_file, stamp, rows in snapshots:
            fetched = datetime.fromtimestamp(stamp + 5, tz=timezone.utc)
            full = [
                {
                    **r,
                    "source_file": source_file,
                    "feed_timestamp": stamp,
                    "fetch_timestamp": fetched,
                }
                for r in rows
            ]
            writer.write_table(pa.Table.from_pylist(full, schema))
    return path


def test_snapshot_entities_are_contiguous_runs_not_ids(tmp_path: Path) -> None:
    # Two vehicles report the same trip: two entities sharing the trip id as entity id.
    rows = [
        _tu_row(vehicle_id="V1", stop_id="S1", stop_sequence=1),
        _tu_row(vehicle_id="V1", stop_id="S2", stop_sequence=2),
        _tu_row(vehicle_id="V2", stop_id="S1"),
        _tu_row(entity_id="OTHER", trip_id="OTHER", vehicle_id="V3", stop_id="S5"),
    ]
    path = _archive(tmp_path / "tu.parquet", [("a.pb", 100, rows), ("b.pb", 130, rows[:1])])
    snap = encode_snapshot(str(path), "trip_updates", 0)
    assert (snap.source_file, snap.feed_timestamp, snap.fetch_timestamp_us) == (
        "a.pb",
        100,
        105_000_000,
    )
    assert [len(decode_trip_update(v)) for _, v in snap.messages] == [2, 1, 1]
    assert [k for k, _ in snap.messages] == [b"MQ_D6-Weekday-SDon-084000_M15_401"] * 2 + [b"OTHER"]
    # The independent vectorised count agrees, per snapshot.
    assert entity_counts(path, "trip_updates") == {"a.pb": 3, "b.pb": 1}


def test_a_row_group_holding_two_snapshots_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.parquet"
    good = _archive(
        tmp_path / "good.parquet", [("a.pb", 100, [_tu_row()]), ("b.pb", 130, [_tu_row()])]
    )
    pq.write_table(pq.read_table(good), path)  # rewritten as a single row group
    with pytest.raises(ValueError, match="2 snapshots"):
        encode_snapshot(str(path), "trip_updates", 0)


def test_decoded_rows_fit_the_canonical_schemas() -> None:
    header = {
        "feed": "trip_updates.bus",
        "source_file": "a.pb",
        "feed_timestamp": 100,
        "fetch_timestamp_us": 105_000_000,
    }
    rows = [{**header, **r} for r in _roundtrip([_tu_row()])]
    assert pa.Table.from_pylist(rows, TRIP_UPDATE_ROW).num_rows == 1
    from google.transit import gtfs_realtime_pb2 as rt

    entity = rt.FeedEntity(id="E1")
    entity.vehicle.vehicle.id = "V1"
    vehicle = {**header, **decode_vehicle(entity.SerializeToString())}
    assert pa.Table.from_pylist([vehicle], VEHICLE_ROW).num_rows == 1
    assert {f.name for f in SNAPSHOT_FIELDS} <= set(TRIP_UPDATE_ROW.names) & set(VEHICLE_ROW.names)


def _snaps(n: int = 20, per: int = 50) -> list[EncodedSnapshot]:
    return [
        EncodedSnapshot(
            "x",
            i,
            f"s{i}.pb",
            100 + 30 * i,
            0,
            per,
            [(f"k{j}".encode(), f"{i}-{j}".encode()) for j in range(per)],
        )
        for i in range(n)
    ]


def _run(f: faults_mod.Faults) -> list[tuple[int, list[bytes]]]:
    return [
        (s.feed_timestamp, [v for _, v, _ in out])
        for s, out in faults_mod.apply(f, "feed", _snaps())
    ]


def test_faults_are_seeded_and_deterministic() -> None:
    f = faults_mod.Faults(seed=7, duplicate_rate=0.1, lateness_s=30, late_share=0.1)
    assert _run(f) == _run(f)
    assert _run(f) != _run(
        faults_mod.Faults(seed=8, duplicate_rate=0.1, lateness_s=30, late_share=0.1)
    )


def test_no_faults_changes_nothing() -> None:
    assert _run(faults_mod.Faults()) == [
        (s.feed_timestamp, [v for _, v in s.messages]) for s in _snaps()
    ]


def test_duplicates_outage_and_lateness() -> None:
    dup = sum(len(v) for _, v in _run(faults_mod.Faults(seed=1, duplicate_rate=0.2)))
    assert 1000 < dup < 1400  # 1000 messages, ~20 % emitted twice
    out = _run(faults_mod.Faults(outage=(100 + 30 * 5, 90)))  # snapshots 5, 6, 7 dropped
    assert [t for t, _ in out] == [100 + 30 * i for i in range(20) if i not in (5, 6, 7)]
    late = faults_mod.apply(
        faults_mod.Faults(seed=3, lateness_s=30, late_share=0.5), "feed", _snaps()
    )
    moved = [
        (snap.feed_timestamp, origin.feed_timestamp)
        for snap, out in late
        for _, _, origin in out
        if origin.feed_timestamp != snap.feed_timestamp
    ]
    assert moved and all(sent - origin >= 30 for sent, origin in moved)


def test_faults_only_reach_fault_topics() -> None:
    faulted = faults_mod.Faults(duplicate_rate=0.1)
    with pytest.raises(ValueError):
        check_topic_prefix("rt", faulted)
    with pytest.raises(ValueError):
        check_topic_prefix("faults", faults_mod.Faults())
    check_topic_prefix("faults", faulted)
    check_topic_prefix("rt", faults_mod.Faults())


def test_pacer_releases_on_scaled_feed_time() -> None:
    now = [1000.0]
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    pacer = Pacer(speed=60, sim_start=5000, wall_start=1000.0, clock=lambda: now[0], sleep=sleep)
    for ts in (5000, 5060, 5120):
        pacer.wait(ts)
    assert slept == [1.0, 1.0] and pacer.lags == [0.0, 0.0, 0.0]
    now[0] += 5  # a slow send makes the next snapshot late, never early
    pacer.wait(5180)
    assert pacer.lags[-1] == pytest.approx(4.0)


def test_parallel_encoding_matches_sequential(tmp_path: Path) -> None:
    snaps = [
        (f"s{i}.pb", 100 + 30 * i, [_tu_row(vehicle_id=f"V{j}", stop_id=f"S{i}") for j in range(3)])
        for i in range(6)
    ]
    path = _archive(tmp_path / "tu.parquet", snaps)
    feed = next(f for f in FEEDS if f.name == "trip_updates.bus")
    parallel = [(s.source_file, s.messages) for s in encoded_snapshots(feed, [path], workers=2)]
    sequential = [
        (s.source_file, s.messages)
        for s in (encode_snapshot(str(path), "trip_updates", g) for g in range(6))
    ]
    assert parallel == sequential


def test_murmur2_matches_the_java_client() -> None:
    # Vectors from Kafka's UtilsTest: keys land on the partitions a Java producer would choose.
    assert murmur2(b"21") == -973932308
    assert murmur2(b"foobar") == -790332482
    assert murmur2(b"a-little-bit-long-string") == -985981536
    assert murmur2(b"a-little-bit-longer-string") == -1486304829
    assert murmur2(b"lkjh234lh9fiuh90y23oiuhsafujhadof229phr9h19h89h8") == -58897971
    assert murmur2(b"abc") == 479470107
    assert all(0 <= partition_for(k.encode()) < 6 for k in ("a", "b", "M15"))


def test_entities_split_on_any_entity_level_change(tmp_path: Path) -> None:
    rows = [
        _tu_row(stop_id="S1", stop_sequence=1),
        _tu_row(stop_id="S2", stop_sequence=2),
        _tu_row(stop_id="S1", stop_sequence=1),  # same trip and vehicle, sequence restarts
        _tu_row(stop_id="S2", stop_sequence=2, trip_timestamp=1_790_085_630),  # new timestamp
    ]
    path = _archive(tmp_path / "tu.parquet", [("a.pb", 100, rows)])
    snap = encode_snapshot(str(path), "trip_updates", 0)
    assert [len(decode_trip_update(v)) for _, v in snap.messages] == [2, 1, 1]
    assert entity_counts(path, "trip_updates") == {"a.pb": 3}


class _Message:
    def __init__(
        self,
        topic: str,
        partition: int,
        offset: int,
        key: bytes,
        value: bytes,
        headers: list[tuple[str, bytes]],
    ) -> None:
        self._t, self._p, self._o, self._k, self._v, self._h = (
            topic,
            partition,
            offset,
            key,
            value,
            headers,
        )

    def topic(self) -> str:
        return self._t

    def partition(self) -> int:
        return self._p

    def offset(self) -> int:
        return self._o

    def key(self) -> bytes:
        return self._k

    def value(self) -> bytes:
        return self._v

    def headers(self) -> list[tuple[str, bytes]]:
        return self._h

    def error(self) -> None:
        return None


class _Producer:
    """Stand-in for confluent_kafka.Producer: keyed murmur2 partitions, per-partition offsets."""

    def __init__(self, fail_after: int | None = None) -> None:
        self.log: list[_Message] = []
        self.pending: list[tuple[Any, _Message]] = []
        self.offsets: dict[tuple[str, int], int] = {}
        self.fail_after = fail_after

    def produce(
        self,
        topic: str,
        value: bytes,
        key: bytes,
        headers: list[tuple[str, bytes]],
        on_delivery: Any,
    ) -> None:
        partition = 0 if ".snapshots." in topic else partition_for(key)
        offset = self.offsets.get((topic, partition), 0)
        self.offsets[(topic, partition)] = offset + 1
        message = _Message(topic, partition, offset, key, value, headers)
        self.log.append(message)
        self.pending.append((on_delivery, message))

    def poll(self, _timeout: float) -> int:
        for callback, message in self.pending:
            failed = self.fail_after is not None and len(self.log) > self.fail_after
            callback("broker unavailable" if failed else None, message)
        self.pending = []
        return 0

    def flush(self, _timeout: float) -> int:
        self.poll(0)
        return 0


def _feed(name: str = "trip_updates.bus") -> Any:
    return next(f for f in FEEDS if f.name == name)


def test_replay_feed_sends_messages_markers_and_lineage(tmp_path: Path) -> None:
    producer = _Producer()
    lineage = tmp_path / "lineage.parquet"
    lineage.write_text("stale")  # an earlier replay's lineage must not survive
    report = replay_feed(
        _feed(), iter(_snaps(4, 10)), producer, "rt", Pacer(0, 0, 0), faults_mod.Faults(), lineage
    )
    data = [m for m in producer.log if m.topic() == "rt.trip_updates.bus"]
    markers = [m for m in producer.log if m.topic() == marker_topic("rt", _feed())]
    assert (report.messages, report.acknowledged, len(data), len(markers)) == (44, 44, 40, 4)
    assert dict(data[0].headers())["source_file"] == b"s0.pb"
    assert all(m.partition() == partition_for(m.key()) for m in data)
    spans = pq.read_table(lineage).to_pylist()
    assert sum(s["messages"] for s in spans) == 40
    assert {s["source_file"] for s in spans} == {f"s{i}.pb" for i in range(4)}


def test_late_messages_keep_their_snapshot_in_lineage(tmp_path: Path) -> None:
    producer = _Producer()
    lineage = tmp_path / "lineage.parquet"
    faults = faults_mod.Faults(seed=2, lateness_s=30, late_share=0.5)
    replay_feed(_feed(), iter(_snaps(6, 10)), producer, "faults", Pacer(0, 0, 0), faults, lineage)
    by_snapshot: dict[str, int] = {}
    for span in pq.read_table(lineage).to_pylist():
        by_snapshot[span["source_file"]] = (
            by_snapshot.get(span["source_file"], 0) + span["messages"]
        )
    sent = [dict(m.headers())["source_file"].decode() for m in producer.log if m.headers()]
    for name, count in by_snapshot.items():
        assert sent.count(name) == count  # attributed to its origin, wherever it was sent


def test_replay_feed_refuses_faults_on_real_topics_and_stops_on_delivery_errors() -> None:
    with pytest.raises(ValueError):
        replay_feed(
            _feed(),
            iter(_snaps(1)),
            _Producer(),
            "rt",
            Pacer(0, 0, 0),
            faults_mod.Faults(duplicate_rate=0.5),
            None,
        )
    with pytest.raises(RuntimeError, match="delivery failed"):
        replay_feed(
            _feed(),
            iter(_snaps(5, 10)),
            _Producer(fail_after=15),
            "rt",
            Pacer(0, 0, 0),
            faults_mod.Faults(),
            None,
        )


def _vehicle_archive(path: Path) -> Path:
    rows = [
        {
            "entity_id": f"E{i}",
            "vehicle_id": f"V{i}",
            "trip_id": "T1",
            "latitude": 40.75,
            "longitude": -73.98,
            "stop_id": "S1",
            "timestamp": 100 + i,
        }
        for i in range(3)
    ]
    schema = pa.schema(
        [f for f in VEHICLE_ROW if f.name not in ("feed", "fetch_timestamp_us")]
        + [
            pa.field("fetch_timestamp", pa.timestamp("us", tz="UTC")),
            pa.field("multi_carriage_details_json", pa.string()),
        ]
    )
    fetched = datetime.fromtimestamp(105, tz=timezone.utc)
    full = [
        {
            **r,
            "source_file": "v.pb",
            "feed_timestamp": 100,
            "fetch_timestamp": fetched,
            "multi_carriage_details_json": None,
        }
        for r in rows
    ]
    pq.write_table(pa.Table.from_pylist(full, schema), path)
    return path


def test_vehicle_positions_and_the_fidelity_comparator(tmp_path: Path) -> None:
    path = _vehicle_archive(tmp_path / "vp.parquet")
    feed = _feed("vehicle_positions.bus")
    snap = encode_snapshot(str(path), "vehicle_positions", 0)
    assert entity_counts(path, "vehicle_positions") == {"v.pb": 3}
    messages = [
        _Message("rt.vehicle_positions.bus", partition_for(k), i, k, v, [])
        for i, (k, v) in enumerate(snap.messages)
    ]
    assert sorted(decoded_entities(feed, messages)) == sorted(archive_entities(feed, str(path), 0))
    wrong_key = [_Message("t", 0, 0, b"other", messages[0].value(), [])] + messages[1:]
    assert sorted(decoded_entities(feed, wrong_key)) != sorted(archive_entities(feed, str(path), 0))
    assert uncarried_columns(path, "vehicle_positions") == []  # the extra column is all NULL


def test_a_snapshot_without_fetch_time_is_replayed_with_an_empty_header(tmp_path: Path) -> None:
    path = _archive(tmp_path / "tu.parquet", [("a.pb", 100, [_tu_row()])])
    table = pq.read_table(path)
    nulls = pa.nulls(table.num_rows, pa.timestamp("us", tz="UTC"))
    pq.write_table(
        table.set_column(table.column_names.index("fetch_timestamp"), "fetch_timestamp", nulls),
        path,
    )
    snap = encode_snapshot(str(path), "trip_updates", 0)
    assert snap.fetch_timestamp_us is None
    producer = _Producer()
    replay_feed(_feed(), iter([snap]), producer, "rt", Pacer(0, 0, 0), faults_mod.Faults(), None)
    data = [m for m in producer.log if m.topic() == "rt.trip_updates.bus"]
    assert dict(data[0].headers())["fetch_timestamp_us"] == b""
