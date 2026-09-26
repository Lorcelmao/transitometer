"""Replay one time range of archived vehicle positions into Kafka (runs inside the Spark image).

Usage: python -m transitometer.replay.produce --parquet <file> --start <ISO UTC> --end <ISO UTC>
Prints one JSON summary line. Pacing and fault injection arrive with the full harness.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from typing import Any

import pyarrow.parquet as pq

from transitometer.replay.encode import VEHICLE_COLUMNS, snapshots, vehicle_entity

HEADER_FEED = "feed"
HEADER_FEED_TIMESTAMP = "feed_timestamp"
HEADER_SOURCE_FILE = "source_file"


def epoch(text: str) -> int:
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp must carry a UTC offset: {text}")
    return int(parsed.timestamp())


def ensure_topic(bootstrap: str, topic: str, partitions: int) -> None:
    from confluent_kafka.admin import AdminClient, NewTopic

    admin = AdminClient({"bootstrap.servers": bootstrap})
    if topic in admin.list_topics(timeout=30).topics:
        return
    futures = admin.create_topics([NewTopic(topic, num_partitions=partitions)])
    futures[topic].result(timeout=30)


def replay(args: argparse.Namespace) -> dict[str, Any]:
    from confluent_kafka import Producer

    start, end = epoch(args.start), epoch(args.end)
    table = pq.read_table(
        args.parquet,
        columns=list(VEHICLE_COLUMNS),
        filters=[("feed_timestamp", ">=", start), ("feed_timestamp", "<", end)],
    )
    ensure_topic(args.bootstrap, args.topic, args.partitions)
    producer = Producer(
        {
            "bootstrap.servers": args.bootstrap,
            "compression.type": "zstd",
            "linger.ms": 20,
            "acks": "all",
            "enable.idempotence": True,
        }
    )
    sent = 0
    snapshot_count = 0
    delivered = 0
    failures: list[str] = []

    def on_delivery(error: Any, _message: Any) -> None:
        """Broker acknowledgement per message: the only proof a message reached Kafka."""
        nonlocal delivered
        if error is not None:
            failures.append(str(error))
        else:
            delivered += 1

    for snap in snapshots(table.to_pylist()):
        snapshot_count += 1
        headers = [
            (HEADER_FEED, args.feed.encode()),
            (HEADER_FEED_TIMESTAMP, str(snap.feed_timestamp).encode()),
            (HEADER_SOURCE_FILE, snap.source_file.encode()),
        ]
        for row in snap.rows:
            key = (row.get("vehicle_id") or row["entity_id"]).encode()
            payload = vehicle_entity(row).SerializeToString()
            while True:
                try:
                    producer.produce(
                        args.topic, value=payload, key=key, headers=headers, on_delivery=on_delivery
                    )
                    break
                except BufferError:  # local queue full: let the client drain, then retry
                    producer.poll(0.5)
            sent += 1
        producer.poll(0)
    unsent = producer.flush(120)
    if unsent or failures or delivered != sent:
        raise RuntimeError(
            f"delivery incomplete: sent {sent}, acknowledged {delivered}, still queued {unsent}, "
            f"errors {failures[:3]}"
        )
    return {
        "rows": table.num_rows,
        "snapshots": snapshot_count,
        "messages": sent,
        "acknowledged": delivered,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parquet", required=True)
    parser.add_argument("--start", required=True, help="inclusive, ISO-8601 UTC")
    parser.add_argument("--end", required=True, help="exclusive, ISO-8601 UTC")
    parser.add_argument("--topic", required=True)
    parser.add_argument("--feed", default="mta_bus")
    parser.add_argument("--bootstrap", default="kafka:9092")
    parser.add_argument("--partitions", type=int, default=6)
    print(json.dumps(replay(parser.parse_args(argv))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
