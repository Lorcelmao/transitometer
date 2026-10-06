"""Axis A, Flink arm: W1 and W2 from the passage stream (PyFlink, Table API + DataStream).

Reads `rt.passages` between the offsets recorded by the producer (a bounded source: the job ends
when it has read them, and the final watermark flushes every window and timer) and writes:
  kpi.flink.w1   1-minute tumbling event-time windows of arrival delay per (route, stop) (SQL)
  kpi.flink.w2   the BR2 headway of each passage (KeyedProcessFunction with event-time timers,
                 the same transitometer.axis_a.headway_state step as the Spark arm)

Event time is the observed arrival; the watermark trails it by 120 s, as in the Spark arm.

Usage (inside the Flink image):
  flink run -py flink_job.py --offsets '{"0": [start, end], ...}' [--bootstrap kafka:9092]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Iterator
from typing import Any

from pyflink.common import Row, Types
from pyflink.datastream import KeyedProcessFunction, StreamExecutionEnvironment
from pyflink.datastream.state import ValueStateDescriptor
from pyflink.table import StreamTableEnvironment

from transitometer.axis_a import headway_state as hs

TOPIC = "rt.passages"
END = "__end__"
WATERMARK_S = 120
PARALLELISM = 8
PASSAGE_COLUMNS = (
    ("grp", "STRING"),
    ("service_date", "STRING"),
    ("route_id", "STRING"),
    ("stop_id", "STRING"),
    ("service_hour", "BIGINT"),
    ("trip_key", "STRING"),
    ("trip_id", "STRING"),
    ("unit", "STRING"),
    ("source", "STRING"),
    ("observed_arrival", "BIGINT"),
    ("delay_s", "BIGINT"),
    ("ref_headway_s", "DOUBLE"),
)
PASSAGE_FIELDS = [name for name, _ in PASSAGE_COLUMNS]
LONGS = ("service_hour", "observed_arrival", "headway_s")
W2_TYPES = [
    Types.LONG() if f in LONGS else Types.DOUBLE() if f == "ref_headway_s" else Types.STRING()
    for f in hs.OUTPUT_FIELDS
]
W2_SQL_TYPES = [
    "BIGINT" if f in LONGS else "DOUBLE" if f == "ref_headway_s" else "STRING"
    for f in hs.OUTPUT_FIELDS
]


def offsets_option(offsets: dict[str, list[int]], index: int) -> str:
    return ";".join(f"partition:{p},offset:{b[index]}" for p, b in sorted(offsets.items()))


def source_ddl(bootstrap: str, offsets: dict[str, list[int]]) -> str:
    columns = ",\n  ".join(f"`{n}` {t}" for n, t in PASSAGE_COLUMNS)
    return f"""
CREATE TABLE passages (
  {columns},
  et AS TO_TIMESTAMP_LTZ(observed_arrival, 0),
  WATERMARK FOR et AS et - INTERVAL '{WATERMARK_S}' SECOND(3)
) WITH (
  'connector' = 'kafka',
  'topic' = '{TOPIC}',
  'properties.bootstrap.servers' = '{bootstrap}',
  'properties.group.id' = 'axis-a-flink',
  'scan.startup.mode' = 'specific-offsets',
  'scan.startup.specific-offsets' = '{offsets_option(offsets, 0)}',
  'scan.bounded.mode' = 'specific-offsets',
  'scan.bounded.specific-offsets' = '{offsets_option(offsets, 1)}',
  'format' = 'json',
  'json.fail-on-missing-field' = 'false'
)"""


def sink_ddl(name: str, topic: str, columns: str, bootstrap: str) -> str:
    return f"""
CREATE TABLE {name} ({columns}) WITH (
  'connector' = 'kafka',
  'topic' = '{topic}',
  'properties.bootstrap.servers' = '{bootstrap}',
  'format' = 'json'
)"""


W1_COLUMNS = (
    "grp STRING, service_date STRING, route_id STRING, stop_id STRING, window_start BIGINT, "
    "delays BIGINT, delay_sum_s BIGINT, mean_delay_s DOUBLE, min_delay_s BIGINT, "
    "max_delay_s BIGINT, stddev_delay_s DOUBLE"
)
# Windows are aligned to the epoch minute, so the window start is any member's arrival rounded
# down to the minute.
W1_INSERT = f"""
INSERT INTO kpi_w1
SELECT grp, service_date, route_id, stop_id,
       MIN(observed_arrival) - MOD(MIN(observed_arrival), 60) AS window_start,
       COUNT(*) AS delays,
       SUM(delay_s) AS delay_sum_s,
       AVG(CAST(delay_s AS DOUBLE)) AS mean_delay_s,
       MIN(delay_s) AS min_delay_s,
       MAX(delay_s) AS max_delay_s,
       STDDEV_POP(CAST(delay_s AS DOUBLE)) AS stddev_delay_s
FROM TABLE(TUMBLE(TABLE passages, DESCRIPTOR(et), INTERVAL '1' MINUTE))
WHERE delay_s IS NOT NULL AND grp <> '{END}'
GROUP BY grp, service_date, route_id, stop_id, window_start, window_end
"""


class Headways(KeyedProcessFunction):  # type: ignore[misc]
    """W2 per (grp, service_date, route_id, stop_id), with the shared headway_state step."""

    def open(self, runtime_context: Any) -> None:
        self.saved = runtime_context.get_state(ValueStateDescriptor("headway", Types.STRING()))

    def _load(self) -> hs.HeadwayState:
        raw = self.saved.value()
        if raw is None:
            return hs.HeadwayState()
        body = json.loads(raw)
        return hs.HeadwayState(body["last"], body["buffer"], body["late"])

    def _store(self, state: hs.HeadwayState) -> None:
        self.saved.update(
            json.dumps({"last": state.last, "buffer": state.buffer, "late": state.late})
        )

    def _emit(self, state: hs.HeadwayState, ctx: Any, watermark_ms: int) -> Iterator[Row]:
        for row in hs.release(state, watermark_ms / 1000):
            yield Row(*(row[f] for f in hs.OUTPUT_FIELDS))
        earliest = hs.earliest(state)
        if earliest is not None:
            ctx.timer_service().register_event_time_timer((earliest + 1) * 1000)
        self._store(state)

    def process_element(self, value: Row, ctx: Any) -> Iterator[Row]:
        state = self._load()
        hs.add(state, [{f: value[f] for f in PASSAGE_FIELDS}])
        yield from self._emit(state, ctx, ctx.timer_service().current_watermark())

    def on_timer(self, timestamp: int, ctx: Any) -> Iterator[Row]:
        yield from self._emit(self._load(), ctx, ctx.timer_service().current_watermark())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offsets", required=True, help='JSON {"partition": [start, end]}')
    parser.add_argument("--bootstrap", default="kafka:9092")
    args = parser.parse_args(argv)
    offsets: dict[str, list[int]] = json.loads(args.offsets)

    env = StreamExecutionEnvironment.get_execution_environment()
    env.set_parallelism(PARALLELISM)
    env.enable_checkpointing(10_000)
    t_env = StreamTableEnvironment.create(env)
    t_env.execute_sql(source_ddl(args.bootstrap, offsets))
    t_env.execute_sql(sink_ddl("kpi_w1", "kpi.flink.w1", W1_COLUMNS, args.bootstrap))
    w2_columns = ", ".join(f"{n} {t}" for n, t in zip(hs.OUTPUT_FIELDS, W2_SQL_TYPES, strict=True))
    t_env.execute_sql(sink_ddl("kpi_w2", "kpi.flink.w2", w2_columns, args.bootstrap))

    passages = t_env.to_data_stream(t_env.from_path("passages"))
    w2 = (
        passages.filter(lambda r: r["grp"] != END)
        .key_by(
            lambda r: f"{r['grp']}|{r['service_date']}|{r['route_id']}|{r['stop_id']}",
            key_type=Types.STRING(),
        )
        .process(Headways(), output_type=Types.ROW_NAMED(list(hs.OUTPUT_FIELDS), W2_TYPES))
    )
    statements = t_env.create_statement_set()
    statements.add_insert_sql(W1_INSERT)
    statements.add_insert("kpi_w2", t_env.from_data_stream(w2))
    started = time.perf_counter()
    statements.attach_as_datastream()
    env.execute("axis-a-flink")
    print(
        json.dumps(
            {
                "engine": "Flink (PyFlink)",
                "topic": TOPIC,
                "watermark": f"{WATERMARK_S} seconds",
                "parallelism": PARALLELISM,
                "drained_s": round(time.perf_counter() - started, 1),
                "offsets": offsets,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
