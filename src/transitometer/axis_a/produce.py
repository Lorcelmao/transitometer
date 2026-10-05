"""Produce the Axis A passage stream into Kafka, and verify it (runs in the Spark tooling image).

One JSON message per passage, in event-time order (the order of passages.parquet), keyed by
`grp|service_date|route_id|stop_id` so every passage of one stop lands in one partition. A final
end-of-stream message (key and grp `__end__`, event time one day after the last passage) lets a
micro-batch engine advance its watermark past every real passage; both engines discard it.

The record (`results/axis-a-produce.json`) holds per partition the start and end offsets, the
message count and the SHA-256 of the values in offset order. The partitioner and the send order
are deterministic, so `verify` can recompute the same digests from the topic.

Usage: python -m transitometer.axis_a.produce produce --parquet <passages.parquet> [--fresh]
       python -m transitometer.axis_a.produce verify --record <record.json>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections.abc import Iterable, Iterator
from typing import Any

import pyarrow.parquet as pq

TOPIC = "rt.passages"
PARTITIONS = 6
END = "__end__"
END_OFFSET_S = 86_400
FIELDS = (
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
    "delay_s",
    "ref_headway_s",
)
PRODUCER_CONFIG = {
    "compression.type": "zstd",
    "linger.ms": 20,
    "acks": "all",
    "enable.idempotence": True,
    "partitioner": "murmur2_random",  # Java-client compatible key hashing, as the main replay
}


def key_of(row: dict[str, Any]) -> bytes:
    return "|".join(str(row[f]) for f in ("grp", "service_date", "route_id", "stop_id")).encode()


def value_of(row: dict[str, Any]) -> bytes:
    """Canonical JSON: fixed field order, no spaces; NULL stays null."""
    return json.dumps({f: row[f] for f in FIELDS}, separators=(",", ":")).encode()


def end_marker(last_arrival: int) -> dict[str, Any]:
    row: dict[str, Any] = dict.fromkeys(FIELDS)
    row.update(grp=END, service_date=END, route_id=END, stop_id=END, trip_key=END)
    row.update(trip_id=END, unit=END, source=END, observed_arrival=last_arrival + END_OFFSET_S)
    return row


def passages(path: str) -> Iterator[dict[str, Any]]:
    for batch in pq.ParquetFile(path).iter_batches(batch_size=50_000, columns=list(FIELDS)):
        yield from batch.to_pylist()


def offsets(bootstrap: str, topic: str) -> dict[int, tuple[int, int]]:
    from confluent_kafka import Consumer, TopicPartition

    consumer = Consumer({"bootstrap.servers": bootstrap, "group.id": "axis-a-offsets"})
    try:
        meta = consumer.list_topics(topic, timeout=30).topics[topic]
        return {
            p: consumer.get_watermark_offsets(TopicPartition(topic, p), timeout=30)
            for p in sorted(meta.partitions)
        }
    finally:
        consumer.close()


def recreate(bootstrap: str, topic: str, partitions: int) -> None:
    from confluent_kafka.admin import AdminClient, NewTopic

    admin = AdminClient({"bootstrap.servers": bootstrap})
    if topic in admin.list_topics(timeout=30).topics:
        admin.delete_topics([topic], operation_timeout=60)[topic].result(timeout=60)
        while topic in admin.list_topics(timeout=30).topics:
            time.sleep(1)
    while True:  # deletion completes asynchronously on the broker
        try:
            admin.create_topics([NewTopic(topic, num_partitions=partitions)])[topic].result(60)
            return
        except Exception as error:  # noqa: BLE001 - TOPIC_ALREADY_EXISTS while still deleting
            if "already exists" not in str(error).lower():
                raise
            time.sleep(1)


def produce(rows: Iterable[dict[str, Any]], bootstrap: str, topic: str) -> dict[str, Any]:
    from confluent_kafka import Producer

    before = offsets(bootstrap, topic)
    producer = Producer({"bootstrap.servers": bootstrap, **PRODUCER_CONFIG})
    sent = delivered = 0
    failures: list[str] = []
    last_arrival = 0
    started = time.perf_counter()

    def on_delivery(error: Any, _message: Any) -> None:
        nonlocal delivered
        if error is not None:
            failures.append(str(error))
        else:
            delivered += 1

    def send(row: dict[str, Any]) -> None:
        nonlocal sent
        while True:
            try:
                producer.produce(
                    topic, value=value_of(row), key=key_of(row), on_delivery=on_delivery
                )
                break
            except BufferError:  # local queue full: let the client drain, then retry
                producer.poll(0.5)
        sent += 1
        if sent % 250_000 == 0:
            producer.poll(0)
            print(f"progress {sent:,} passages sent", file=sys.stderr, flush=True)

    for row in rows:
        last_arrival = max(last_arrival, int(row["observed_arrival"]))
        send(row)
        producer.poll(0)
    passages_sent = sent
    send(end_marker(last_arrival))
    unsent = producer.flush(300)
    if unsent or failures or delivered != sent:
        raise RuntimeError(
            f"delivery incomplete: sent {sent}, acknowledged {delivered}, queued {unsent}, "
            f"errors {failures[:3]}"
        )
    after = offsets(bootstrap, topic)
    bounds = {
        str(p): {"start": before.get(p, (0, 0))[1], "end": after[p][1]} for p in sorted(after)
    }
    digests = digest_topic(bootstrap, topic, bounds)
    return {
        "topic": topic,
        "passages": passages_sent,
        "messages": sent,
        "last_arrival": last_arrival,
        "produce_s": round(time.perf_counter() - started, 1),
        "partitions": {p: {**bounds[p], **digests[p]} for p in bounds},
    }


def digest_topic(
    bootstrap: str, topic: str, partitions: dict[str, dict[str, int]]
) -> dict[str, dict[str, Any]]:
    """Per partition: message count and SHA-256 of the values from start to end offset."""
    from confluent_kafka import Consumer, TopicPartition

    result: dict[str, dict[str, Any]] = {}
    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": "axis-a-verify",
            "enable.auto.commit": False,
        }
    )
    try:
        for p, bounds in partitions.items():
            start, end = bounds["start"], bounds["end"]
            digest = hashlib.sha256()
            count = 0
            if end > start:
                consumer.assign([TopicPartition(topic, int(p), start)])
                while count < end - start:
                    message = consumer.poll(10)
                    if message is None:
                        raise RuntimeError(f"partition {p}: timed out at {start + count}")
                    if message.error():
                        raise RuntimeError(str(message.error()))
                    digest.update(message.value())
                    digest.update(b"\n")
                    count += 1
                consumer.unassign()
            result[p] = {"messages": count, "sha256": digest.hexdigest()}
    finally:
        consumer.close()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("produce")
    make.add_argument("--parquet", required=True)
    make.add_argument("--fresh", action="store_true", help="delete and recreate the topic")
    check = sub.add_parser("verify")
    check.add_argument("--record", required=True, help="JSON written by produce")
    for p in (make, check):
        p.add_argument("--bootstrap", default="kafka:9092")
        p.add_argument("--topic", default=TOPIC)
    args = parser.parse_args(argv)
    if args.command == "produce":
        if args.fresh:
            recreate(args.bootstrap, args.topic, PARTITIONS)
        print(json.dumps(produce(passages(args.parquet), args.bootstrap, args.topic)))
        return 0
    with open(args.record, encoding="utf-8") as handle:
        record = json.load(handle)
    bounds = {p: {"start": b["start"], "end": b["end"]} for p, b in record["partitions"].items()}
    actual = digest_topic(args.bootstrap, args.topic, bounds)
    expected = {
        p: {"messages": b["messages"], "sha256": b["sha256"]}
        for p, b in record["partitions"].items()
    }
    ok = actual == expected and sum(b["messages"] for b in actual.values()) == record["messages"]
    print(json.dumps({"ok": ok, "messages": sum(b["messages"] for b in actual.values())}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
