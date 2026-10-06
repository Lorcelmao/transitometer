"""Dump an engine's Axis A result topics to Parquet (runs in the Spark tooling image).

Reads kpi.<engine>.w1 and kpi.<engine>.w2 from the beginning to their current end, decodes the
JSON values into the golden table's schema (a field an engine leaves out is NULL) and writes
/data/exports/axis-a/<engine>/w1.parquet and w2.parquet. Kafka sinks deliver at least once, so a
key seen twice keeps one row; the duplicate count is reported, and duplicates with different
values fail the dump.

Usage: python -m transitometer.axis_a.dump --engine spark|flink
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

EXPORTS = Path("/data/exports/axis-a")
KEYS = {
    "w1": ("grp", "service_date", "route_id", "stop_id", "window_start"),
    "w2": ("grp", "service_date", "route_id", "stop_id", "trip_key"),
}


def read_topic(bootstrap: str, topic: str) -> list[dict[str, Any]]:
    from confluent_kafka import Consumer, TopicPartition

    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": f"axis-a-dump-{topic}",
            "enable.auto.commit": False,
        }
    )
    rows: list[dict[str, Any]] = []
    try:
        partitions = consumer.list_topics(topic, timeout=30).topics[topic].partitions
        for p in sorted(partitions):
            low, high = consumer.get_watermark_offsets(TopicPartition(topic, p), timeout=30)
            if high <= low:
                continue
            consumer.assign([TopicPartition(topic, p, low)])
            seen = 0
            while seen < high - low:
                message = consumer.poll(10)
                if message is None:
                    raise RuntimeError(f"{topic}[{p}]: timed out at offset {low + seen}")
                if message.error():
                    raise RuntimeError(str(message.error()))
                rows.append(json.loads(message.value()))
                seen += 1
            consumer.unassign()
    finally:
        consumer.close()
    return rows


def dedupe(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> tuple[list[dict[str, Any]], int]:
    """One row per key; an exact repeat is a redelivery, a differing repeat is an error."""
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    duplicates = 0
    for row in rows:
        key = tuple(row.get(k) for k in keys)
        if key in unique:
            duplicates += 1
            if unique[key] != row:
                raise ValueError(f"conflicting rows for key {key}: {unique[key]} vs {row}")
        else:
            unique[key] = row
    return list(unique.values()), duplicates


def to_table(rows: list[dict[str, Any]], schema: pa.Schema) -> pa.Table:
    columns = {f.name: [r.get(f.name) for r in rows] for f in schema}
    return pa.Table.from_pydict(columns, schema=schema)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, choices=("spark", "flink"))
    parser.add_argument("--bootstrap", default="kafka:9092")
    args = parser.parse_args(argv)
    out = EXPORTS / args.engine
    out.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {"engine": args.engine}
    for workload, keys in KEYS.items():
        topic = f"kpi.{args.engine}.{workload}"
        raw = read_topic(args.bootstrap, topic)
        rows, duplicates = dedupe(raw, keys)
        schema = pq.read_schema(EXPORTS / "golden" / f"{workload}.parquet")
        pq.write_table(to_table(rows, schema), out / f"{workload}.parquet", compression="zstd")
        result[workload] = {"messages": len(raw), "rows": len(rows), "duplicates": duplicates}
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
