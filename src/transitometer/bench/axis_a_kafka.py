"""Axis A benchmark Kafka tools (python3 -m in the tooling container).

  recreate  delete and recreate topics (6 partitions)
  produce   send a slice's send plan at a fixed rate (passages/s) to the partitions the plan
            fixes, then the end marker; check every partition ends at the recorded offset
  dump      write a topic, partitions read to their current end, as Parquet: the decoded JSON
            fields plus partition, offset and the broker append time (append_ms)

Usage: python3 -m transitometer.bench.axis_a_kafka recreate --topics T [T ...]
       python3 -m transitometer.bench.axis_a_kafka produce --run-dir D --rate R
       python3 -m transitometer.bench.axis_a_kafka dump --topic T --out F [--ends JSON]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from transitometer.axis_a.produce import (
    PARTITIONS,
    PRODUCER_CONFIG,
    end_marker,
    key_of,
    offsets,
    recreate,
    value_of,
)


def produce(bootstrap: str, run_dir: Path, rate: float) -> dict[str, Any]:
    from confluent_kafka import Producer

    record = json.loads((run_dir / "record.json").read_text("utf-8"))
    topic = record["topic"]
    config = {k: v for k, v in PRODUCER_CONFIG.items() if k != "partitioner"}
    producer = Producer({"bootstrap.servers": bootstrap, **config, "linger.ms": 5})
    failures: list[str] = []

    def on_delivery(error: Any, _message: Any) -> None:
        if error is not None:
            failures.append(str(error))

    def send(row: dict[str, Any], partition: int) -> None:
        while True:
            try:
                producer.produce(
                    topic,
                    value=value_of(row),
                    key=key_of(row),
                    partition=partition,
                    on_delivery=on_delivery,
                )
                return
            except BufferError:
                producer.poll(0.05)

    rows = pq.read_table(run_dir / "send.parquet").to_pylist()
    started = time.time()
    behind_max = 0.0
    for index, row in enumerate(rows):
        due = started + index / rate
        wait = due - time.time()
        if wait > 0:
            time.sleep(wait)
        else:
            behind_max = max(behind_max, -wait)
        send(row, int(row["partition"]))
        producer.poll(0)
        if index and index % 50_000 == 0:
            print(f"progress produce {index:,} sent", file=sys.stderr, flush=True)
    finished = time.time()
    send(end_marker(record["last_arrival"]), int(record["end_marker"]["partition"]))
    unsent = producer.flush(120)
    ends = {str(p): hi for p, (_lo, hi) in offsets(bootstrap, topic).items()}
    expected = {p: b["end"] for p, b in record["partitions"].items()}
    return {
        "topic": topic,
        "sent": len(rows) + 1,
        "rate_target": rate,
        "rate_achieved": round(len(rows) / max(finished - started, 1e-9), 1),
        "max_behind_s": round(behind_max, 3),
        "produce_start_ms": int(started * 1000),
        "produce_end_ms": int(finished * 1000),
        "offsets_ok": ends == expected and not unsent and not failures,
        "ends": ends,
        "failures": failures[:3],
    }


def dump(bootstrap: str, topic: str, out: Path, ends: dict[str, int] | None) -> dict[str, Any]:
    """Read every partition from 0 to its end (given, or the current high watermark)."""
    from confluent_kafka import Consumer, TopicPartition

    consumer = Consumer(
        {"bootstrap.servers": bootstrap, "group.id": "bench-dump", "enable.auto.commit": False}
    )
    rows: list[dict[str, Any]] = []
    try:
        highs = ends or {str(p): hi for p, (_lo, hi) in offsets(bootstrap, topic).items()}
        for partition, end in highs.items():
            if end <= 0:
                continue
            consumer.assign([TopicPartition(topic, int(partition), 0)])
            read = 0
            while read < end:
                message = consumer.poll(10)
                if message is None:
                    raise RuntimeError(f"{topic}[{partition}]: timed out at offset {read}")
                if message.error():
                    raise RuntimeError(str(message.error()))
                body = json.loads(message.value())
                body.update(
                    partition=int(partition),
                    offset=message.offset(),
                    append_ms=message.timestamp()[1],
                )
                rows.append(body)
                read = message.offset() + 1
            consumer.unassign()
    finally:
        consumer.close()
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), out)
    return {"topic": topic, "messages": len(rows), "out": str(out)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("recreate")
    make.add_argument("--topics", nargs="+", required=True)
    send = sub.add_parser("produce")
    send.add_argument("--run-dir", required=True)
    send.add_argument("--rate", type=float, required=True)
    read = sub.add_parser("dump")
    read.add_argument("--topic", required=True)
    read.add_argument("--out", required=True)
    read.add_argument("--ends", help='JSON {"partition": end offset}')
    for p in (make, send, read):
        p.add_argument("--bootstrap", default="kafka:9092")
    args = parser.parse_args(argv)
    if args.command == "recreate":
        for topic in args.topics:
            recreate(args.bootstrap, topic, PARTITIONS)
        result: dict[str, Any] = {"recreated": args.topics}
    elif args.command == "produce":
        result = produce(args.bootstrap, Path(args.run_dir), args.rate)
    else:
        ends = json.loads(args.ends) if args.ends else None
        result = dump(args.bootstrap, args.topic, Path(args.out), ends)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
