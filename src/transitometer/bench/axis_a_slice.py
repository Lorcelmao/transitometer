"""Axis A benchmark inputs (host, DuckDB): the slice, its send plan, its record and its golden.

The slice is the first `count` passages of the Axis A passage stream at or after 2026-09-22
07:00 New York time, in the stream's event-time order. The send plan is the order the paced
producer sends them in, with the Kafka partition of each message fixed in advance (md5 of the
stop key, modulo 6), so the record holds every partition's exact end offset before anything is
sent: both engines get the same bounds up front.

Fault plans (labelled synthetic runs, R3) touch a deterministic 1 % of passages (md5 of key and
trip): `late:L` sends each of them at the point where event time has advanced L seconds past
its own; `dup` sends each of them twice in a row. The data itself never changes, so the slice
golden (the frozen golden SQL over exactly the slice) is the reference for every plan.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

from transitometer.axis_a.golden import PASSAGE_ORDER
from transitometer.axis_a.produce import END, END_OFFSET_S, FIELDS, PARTITIONS
from transitometer.golden.runner import Params, render

# 2026-09-22 07:00 in New York (EDT, UTC-4), fixed in UTC so no time-zone database is needed.
START = int(datetime(2026, 9, 22, 11, tzinfo=timezone.utc).timestamp())  # noqa: UP017
TOPIC = "bench.passages"
KEY_SQL = "grp || '|' || service_date || '|' || route_id || '|' || stop_id"
FAULT_SQL = f"(('0x' || substr(md5({KEY_SQL} || '|' || trip_key), 1, 8))::UBIGINT % 100) = 0"


def partition_sql(key: str) -> str:
    return f"(('0x' || substr(md5({key}), 1, 8))::UBIGINT % {PARTITIONS})::INTEGER"


def prepare(passages: Path, out_dir: Path, count: int, plan: str) -> dict[str, Any]:
    """Write slice.parquet, send.parquet, golden w1/w2 and record.json into out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    columns = ", ".join(FIELDS)
    with duckdb.connect() as con:
        con.execute(
            f"CREATE TABLE axis_a_passages AS SELECT {columns}, "
            f"row_number() OVER (ORDER BY {PASSAGE_ORDER}) AS seq "
            f"FROM read_parquet('{passages.as_posix()}') WHERE observed_arrival >= {START} "
            f"ORDER BY {PASSAGE_ORDER} LIMIT {count}"
        )
        got = con.execute("SELECT count(*), max(observed_arrival) FROM axis_a_passages").fetchone()
        if not got or got[0] != count:
            raise ValueError(f"the stream holds fewer than {count} passages after the start")
        last_arrival = int(got[1])
        if plan == "clean" or plan == "late:0":
            order = "SELECT *, observed_arrival AS send_at, 0 AS copy FROM axis_a_passages"
        elif plan.startswith("late:"):
            lateness = int(plan.split(":", 1)[1])
            order = (
                f"SELECT *, observed_arrival + CASE WHEN {FAULT_SQL} THEN {lateness} ELSE 0 END "
                "AS send_at, 0 AS copy FROM axis_a_passages"
            )
        elif plan == "dup":
            order = (
                "SELECT *, observed_arrival AS send_at, 0 AS copy FROM axis_a_passages UNION ALL "
                f"SELECT *, observed_arrival AS send_at, 1 AS copy FROM axis_a_passages "
                f"WHERE {FAULT_SQL}"
            )
        else:
            raise ValueError(f"unknown plan {plan!r}")
        send = out_dir / "send.parquet"
        con.execute(
            f"COPY (SELECT {columns}, {partition_sql(KEY_SQL)} AS partition FROM ({order}) "
            f"ORDER BY send_at, seq, copy) TO '{send.as_posix()}' (FORMAT parquet)"
        )
        faulted = con.execute(f"SELECT count(*) FROM axis_a_passages WHERE {FAULT_SQL}").fetchone()
        per_partition = dict(
            con.execute(
                f"SELECT partition, count(*) FROM read_parquet('{send.as_posix()}') GROUP BY 1"
            ).fetchall()
        )
        marker_key = "|".join([END] * 4)
        marker_partition = con.execute(f"SELECT {partition_sql('?')}", [marker_key]).fetchone()
        assert marker_partition is not None
        per_partition[marker_partition[0]] = per_partition.get(marker_partition[0], 0) + 1
        params = {k: str(v) for k, v in vars(Params()).items()}
        golden = out_dir / "golden"
        golden.mkdir(exist_ok=True)
        for name, step in (("w1", "axis_a_w1.sql"), ("w2", "axis_a_w2.sql")):
            con.execute(render(step, params))
            con.execute(
                f"COPY (SELECT * FROM axis_a_{name} ORDER BY ALL) TO "
                f"'{(golden / f'{name}.parquet').as_posix()}' (FORMAT parquet)"
            )
        golden_rows = {
            name: int(con.execute(f"SELECT count(*) FROM axis_a_{name}").fetchone()[0])  # type: ignore[index]
            for name in ("w1", "w2")
        }
    record = {
        "topic": TOPIC,
        "plan": plan,
        "passages": count,
        "faulted_passages": int(faulted[0]) if faulted else 0,
        "messages": sum(per_partition.values()),
        "start_event_time": START,
        "last_arrival": last_arrival,
        "end_marker": {
            "partition": marker_partition[0],
            "observed_arrival": last_arrival + END_OFFSET_S,
        },
        "partitions": {
            str(p): {"start": 0, "end": int(n)} for p, n in sorted(per_partition.items())
        },
        "send_sha256": hashlib.sha256(send.read_bytes()).hexdigest(),
        "golden_rows": golden_rows,
    }
    (out_dir / "record.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record
