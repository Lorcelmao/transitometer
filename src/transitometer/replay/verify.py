"""Verify a replay against the archive (runs inside the Spark tooling image, after a replay).

  counts     per feed and snapshot: entities counted from the archive (no encoding)
             == messages acknowledged (lineage) == messages read back from Kafka
  markers    exactly one marker per archive snapshot, with the same entity count
  order      per partition, snapshot timestamps never go backwards; lineage spans never overlap
  fidelity   for a seeded sample of snapshots per feed: the messages, read back via the lineage
             offsets, carry the expected keys on the Java-client partitions and decode to the
             archive rows of that snapshot exactly
  coverage   archive columns the replay does not carry are empty (or constant feed-level values)
  digest     SHA-256 of each topic's bytes (offsets, keys, values, headers): equal digests of two
             replays = byte-identical streams

Usage: python -m transitometer.replay.verify --days 2026-09-22 ... [--sample 20]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import time
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from transitometer.replay.archive import (
    FEEDS,
    Feed,
    _entity_runs,
    columns,
    entity_counts,
)
from transitometer.replay.encode import decode_trip_update, decode_vehicle
from transitometer.replay.run import (
    PARTITIONS,
    REAL_PREFIX,
    archive_files,
    data_topic,
    first_timestamp,
    marker_topic,
)

STALL_S = 120  # no message for this long while some are still expected = failure
PROGRESS_EVERY_S = 30


def progress(message: str) -> None:
    """One line on stderr (tasks.py echoes it live)."""
    print(f"progress verify {message}", file=sys.stderr, flush=True)


FEED_LEVEL = ("feed_url", "feed_version", "incrementality")  # constant per archive file


def murmur2(data: bytes) -> int:
    """Kafka's Java-client murmur2 (Utils.murmur2), as a signed 32-bit integer."""
    m, length = 0x5BD1E995, len(data)
    h = (0x9747B28C ^ length) & 0xFFFFFFFF
    for i in range(0, length - length % 4, 4):
        k = int.from_bytes(data[i : i + 4], "little")
        k = (k * m) & 0xFFFFFFFF
        k ^= k >> 24
        k = (k * m) & 0xFFFFFFFF
        h = ((h * m) & 0xFFFFFFFF) ^ k
    tail, rest = length % 4, length - length % 4
    if tail == 3:
        h ^= data[rest + 2] << 16
    if tail >= 2:
        h ^= data[rest + 1] << 8
    if tail >= 1:
        h ^= data[rest]
        h = (h * m) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * m) & 0xFFFFFFFF
    h ^= h >> 15
    return h - (1 << 32) if h & 0x80000000 else h


def partition_for(key: bytes, partitions: int = PARTITIONS) -> int:
    return (murmur2(key) & 0x7FFFFFFF) % partitions


def _polled(consumer: Any, count: int) -> list[Any]:
    """Next batch of messages; a stalled read fails instead of hanging."""
    deadline = time.monotonic() + STALL_S
    while time.monotonic() < deadline:
        batch = consumer.consume(count, timeout=5)
        for message in batch:
            if message.error():
                raise RuntimeError(message.error())
        if batch:
            return list(batch)
    raise TimeoutError(f"no message for {STALL_S} s while reading back the replay")


def _consumer(bootstrap: str) -> Any:
    from confluent_kafka import Consumer

    return Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": "replay-verify",
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
            "fetch.max.bytes": 64 << 20,
        }
    )


def _read(consumer: Any, topic: str) -> Iterator[Any]:
    """Every message of the topic, partition by partition up to the watermark seen at start."""
    from confluent_kafka import TopicPartition

    meta = consumer.list_topics(topic, timeout=30).topics[topic]
    ends = {
        p: consumer.get_watermark_offsets(TopicPartition(topic, p), timeout=30)
        for p in meta.partitions
    }
    consumer.assign([TopicPartition(topic, p, low) for p, (low, _) in ends.items()])
    remaining = {p for p, (low, high) in ends.items() if high > low}
    while remaining:
        for message in _polled(consumer, 10_000):
            p = message.partition()
            if p not in remaining or message.offset() >= ends[p][1]:
                continue  # written after the check started
            if message.offset() == ends[p][1] - 1:
                remaining.discard(p)
            yield message


def read_back(bootstrap: str, topic: str) -> tuple[Counter[str], int, str]:
    """Messages per snapshot (source_file header), how often a partition's snapshot timestamp
    went backwards, and the topic's digest (per partition, in offset order)."""
    consumer = _consumer(bootstrap)
    counts: Counter[str] = Counter()
    digests: dict[int, Any] = {}
    last: dict[int, int] = {}
    backwards = 0
    reported = time.monotonic()
    try:
        for message in _read(consumer, topic):
            if time.monotonic() - reported >= PROGRESS_EVERY_S:
                reported = time.monotonic()
                progress(f"{topic}: {sum(counts.values()):,} messages read back")
            headers = message.headers() or []
            values = dict(headers)
            counts[values["source_file"].decode()] += 1
            p, stamp = message.partition(), int(values["feed_timestamp"])
            backwards += stamp < last.get(p, stamp)
            last[p] = stamp
            digest = digests.setdefault(p, hashlib.sha256())
            digest.update(message.offset().to_bytes(8, "big"))
            parts = [message.key() or b"", message.value() or b""]
            parts += [k.encode() + b"=" + (v or b"") for k, v in headers]
            for part in parts:
                digest.update(len(part).to_bytes(4, "big") + part)
    finally:
        consumer.close()
    whole = hashlib.sha256()
    for p in sorted(digests):
        whole.update(p.to_bytes(4, "big") + digests[p].digest())
    return counts, backwards, whole.hexdigest()


def read_markers(bootstrap: str, topic: str) -> list[dict[str, Any]]:
    consumer = _consumer(bootstrap)
    try:
        return [json.loads(message.value()) for message in _read(consumer, topic)]
    finally:
        consumer.close()


def fetch_snapshot(bootstrap: str, topic: str, spans: list[dict[str, Any]]) -> list[Any]:
    """The messages of one snapshot, located by its lineage offset ranges."""
    from confluent_kafka import TopicPartition

    consumer = _consumer(bootstrap)
    messages: list[Any] = []
    try:
        for span in spans:
            consumer.assign([TopicPartition(topic, span["partition"], span["first_offset"])])
            left = span["last_offset"] - span["first_offset"] + 1
            while left > 0:
                for message in _polled(consumer, min(left, 10_000)):
                    headers = dict(message.headers() or [])
                    if headers["source_file"].decode() == span["source_file"]:
                        messages.append(message)
                    left -= 1
    finally:
        consumer.close()
    return messages


def _canonical(rows: list[dict[str, Any]]) -> str:
    """An entity as one comparable string (row order kept; NULLs and values compare safely)."""
    return json.dumps(rows, sort_keys=True, default=str)


def archive_entities(feed: Feed, path: str, row_group: int) -> list[tuple[bytes, str]]:
    """The snapshot's entities as (expected Kafka key, rows), straight from the archive."""
    table = pq.ParquetFile(path).read_row_group(row_group, columns=columns(feed.kind))
    body = table.drop_columns(["source_file", "feed_timestamp", "fetch_timestamp"]).to_pylist()
    if feed.kind == "vehicle_positions":
        return [((r.get("vehicle_id") or r["entity_id"]).encode(), _canonical([r])) for r in body]
    runs = [body[start:end] for start, end in _entity_runs(table)]
    return [((run[0]["trip_id"] or run[0]["entity_id"]).encode(), _canonical(run)) for run in runs]


def decoded_entities(feed: Feed, messages: list[Any]) -> list[tuple[bytes, str]]:
    out = []
    for message in messages:
        if feed.kind == "vehicle_positions":
            rows = [decode_vehicle(message.value())]
        else:
            rows = decode_trip_update(message.value())
        out.append((message.key(), _canonical(rows)))
    return out


def uncarried_columns(path: Path, kind: str) -> list[str]:
    """Archive columns the replay does not carry that hold data: must be none (row-group
    statistics; feed-level columns may hold one constant value per file)."""
    meta = pq.ParquetFile(path).metadata
    carried = set(columns(kind))
    problems = []
    for index, name in enumerate(meta.schema.to_arrow_schema().names):
        if name in carried or name in ("date", "feed"):  # partition columns
            continue
        values = set()
        for group in range(meta.num_row_groups):
            rows = meta.row_group(group)
            stats = rows.column(index).statistics
            if stats is None:
                problems.append(f"{name}: no statistics")
                break
            if stats.null_count == rows.num_rows:
                continue
            if name not in FEED_LEVEL or not stats.has_min_max or stats.min != stats.max:
                problems.append(name)
                break
            values.add(stats.min)
        if len(values) > 1:
            problems.append(f"{name}: {len(values)} values")
    return problems


def verify(args: argparse.Namespace) -> dict[str, Any]:
    from datetime import date

    days = [date.fromisoformat(d) for d in args.days]
    lineage_dir = Path(args.lineage_dir) / args.prefix
    every_feed = {f.name: archive_files(Path(args.landing), f, days) for f in FEEDS}
    sim_start = min(first_timestamp(paths[0]) for paths in every_feed.values())  # as the replay
    until = sim_start + int(args.minutes * 60) if args.minutes else None
    rng = random.Random(args.seed)
    result: dict[str, Any] = {"prefix": args.prefix, "days": args.days, "feeds": {}}
    for feed in [f for f in FEEDS if not args.feeds or f.name in args.feeds]:
        topic = data_topic(args.prefix, feed)
        progress(f"{feed.name}: counting entities in the archive")
        expected: Counter[str] = Counter()
        uncarried: set[str] = set()
        for path in every_feed[feed.name]:
            expected.update(entity_counts(path, feed.kind, until))
            uncarried.update(uncarried_columns(path, feed.kind))
        lineage_file = lineage_dir / f"{feed.name}.parquet"
        lineage = pq.read_table(lineage_file).to_pylist() if lineage_file.exists() else []
        acknowledged: Counter[str] = Counter()
        overlapping = 0
        by_partition: dict[int, list[tuple[int, int]]] = {}
        for span in lineage:
            acknowledged[span["source_file"]] += span["messages"]
            by_partition.setdefault(span["partition"], []).append(
                (span["first_offset"], span["last_offset"])
            )
        for spans in by_partition.values():
            spans.sort()
            overlapping += sum(b[0] <= a[1] for a, b in zip(spans, spans[1:], strict=False))
        progress(f"{feed.name}: reading back {sum(expected.values()):,} messages from Kafka")
        consumed, backwards, digest = read_back(args.bootstrap, topic)
        markers = read_markers(args.bootstrap, marker_topic(args.prefix, feed))
        marker_counts = Counter(m["source_file"] for m in markers)
        sample = rng.sample(sorted(expected), min(args.sample, len(expected)))
        progress(f"{feed.name}: decoding {len(sample)} sampled snapshots")
        mismatched = []
        for source_file in sample:
            snapshot_spans = [s for s in lineage if s["source_file"] == source_file]
            if not snapshot_spans:
                mismatched.append(f"{source_file}: not in lineage")
                continue
            messages = fetch_snapshot(args.bootstrap, topic, snapshot_spans)
            misplaced = sum(m.partition() != partition_for(m.key()) for m in messages)
            got = sorted(decoded_entities(feed, messages))
            first = snapshot_spans[0]
            want = sorted(archive_entities(feed, first["archive_path"], first["row_group"]))
            if got != want or misplaced:
                mismatched.append(f"{source_file}: rows or keys differ, {misplaced} misplaced")
        result["feeds"][feed.name] = {
            "snapshots": len(expected),
            "messages": sum(expected.values()),
            "acknowledged_equal": acknowledged == expected,
            "consumed_equal": consumed == expected,
            "markers_equal": {m["source_file"]: m["entities"] for m in markers} == dict(expected)
            and all(n == 1 for n in marker_counts.values()),
            "timestamps_backwards": backwards,
            "lineage_overlaps": overlapping,
            "fidelity_sampled": len(sample),
            "fidelity_mismatched": mismatched,
            "uncarried_columns_with_data": sorted(uncarried),
            "stream_sha256": digest,
        }
    result["ok"] = all(
        f["acknowledged_equal"]
        and f["consumed_equal"]
        and f["markers_equal"]
        and not f["timestamps_backwards"]
        and not f["lineage_overlaps"]
        and not f["fidelity_mismatched"]
        and not f["uncarried_columns_with_data"]
        for f in result["feeds"].values()
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--days", nargs="+", required=True)
    parser.add_argument("--feeds", nargs="*", help="subset of feeds to check")
    parser.add_argument("--prefix", default=REAL_PREFIX)
    parser.add_argument("--sample", type=int, default=20, help="snapshots decoded per feed")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--minutes", type=float, default=0, help="as passed to the replay")
    parser.add_argument("--landing", default="/data/landing")
    parser.add_argument("--bootstrap", default="kafka:9092")
    parser.add_argument("--lineage-dir", default="/data/lakehouse/meta/replay_lineage")
    result = verify(parser.parse_args(argv))
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
