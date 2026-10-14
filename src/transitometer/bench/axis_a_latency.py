"""Axis A latency from Kafka append times (docs/benchmark-fairness.md, Axis A).

Inputs are DuckDB relations (Parquet dumps of the topics, each row with its `append_ms`):
  input   the passages as sent (end marker excluded), with grp, service_date, route_id, stop_id,
          trip_key, observed_arrival, append_ms
  w1, w2  an engine's outputs with their own append_ms

W2: each headway is matched to its input passage on (grp, service_date, route_id, stop_id,
trip_key); latency = output append - input append. With duplicated input, the first copy counts.
W1: a window [s, s + 60) can be emitted once the watermark (max event time - 120 s) passes its end,
so its reference is the append time of the first input whose event time is at least s + 180,
that is, the first point at which the running maximum event time reaches it. Windows no real
passage closes (only the end marker) are excluded. Outputs delivered twice (at-least-once) count
once, at their first append. Samples whose reference falls in the warm-up are excluded.
"""

from __future__ import annotations

from typing import Any

import duckdb

KEY = ("grp", "service_date", "route_id", "stop_id")
WATERMARK_S = 120
WINDOW_S = 60
PERCENTILES = tuple(range(0, 101))


def _first(relation: str, keys: tuple[str, ...]) -> str:
    cols = ", ".join(keys)
    return f"(SELECT {cols}, min(append_ms) AS append_ms FROM {relation} GROUP BY {cols})"


def w2_latencies(inp: str, out: str, warmup_ms: int) -> str:
    """A relation of W2 latencies in ms (column `latency_ms`)."""
    keys = (*KEY, "trip_key")
    join = " AND ".join(f"i.{k} = o.{k}" for k in keys)
    return (
        f"(SELECT o.append_ms - i.append_ms AS latency_ms "
        f"FROM {_first(out, keys)} o JOIN {_first(inp, keys)} i ON {join} "
        f"WHERE i.append_ms >= {warmup_ms})"
    )


def w1_latencies(inp: str, out: str, warmup_ms: int) -> str:
    """A relation of W1 latencies in ms (column `latency_ms`)."""
    keys = (*KEY, "window_start")
    running = (
        f"(SELECT append_ms, max(observed_arrival) OVER (ORDER BY append_ms, observed_arrival "
        f"ROWS UNBOUNDED PRECEDING) AS reached FROM {inp})"
    )
    closes = f"(SELECT min(append_ms) AS close_ms, reached FROM {running} GROUP BY reached)"
    needed = WINDOW_S + WATERMARK_S
    windows = f"(SELECT *, window_start + {needed} AS needed FROM {_first(out, keys)})"
    # ASOF: for each window, the smallest running maximum that reaches its close point.
    return (
        f"(SELECT w.append_ms - c.close_ms AS latency_ms FROM {windows} w "
        f"ASOF JOIN {closes} c ON w.needed <= c.reached "
        f"WHERE c.close_ms >= {warmup_ms})"
    )


def distribution(con: duckdb.DuckDBPyConnection, latencies: str) -> dict[str, Any]:
    """Count, p50/p95/p99/max and the 0..100 percentiles (ms) of a latency relation."""
    quantiles = ", ".join(str(p / 100) for p in PERCENTILES)
    row = con.execute(
        f"SELECT count(*), quantile_cont(latency_ms, [{quantiles}]) FROM {latencies}"
    ).fetchone()
    count, values = (row[0], row[1]) if row else (0, None)
    points = [float(v) for v in values] if count and values else []
    return {
        "samples": int(count),
        "p50_ms": points[50] if points else None,
        "p95_ms": points[95] if points else None,
        "p99_ms": points[99] if points else None,
        "max_ms": points[100] if points else None,
        "percentiles_ms": points,
    }
