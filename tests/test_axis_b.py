"""Axis B: the per-engine query adaptations and the suite runner (no engine needed)."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from transitometer.axis_b import dialect
from transitometer.axis_b.runner import run_suite
from transitometer.golden import suite

TIME_TRAVEL = ("q24_version_first_day_vs_latest", "q25_route_change_between_versions")


def test_suite_reads_eleven_tables() -> None:
    assert dialect.tables() == [
        "feed_quality_metrics",
        "headways",
        "route_scorecard",
        "segment_travel_stats",
        "segments",
        "stop_events",
        "stop_hour_reliability",
        "terminal_events",
        "trip_delay_attribution",
        "trip_delivery",
        "warning_decisions",
    ]


@pytest.mark.parametrize("engine", ["spark", "duckdb"])
def test_delta_engines_run_the_frozen_text_except_time_travel(engine: str) -> None:
    for statement in dialect.statements(engine, "stop_events VERSION AS OF 0"):
        if statement.name in TIME_TRAVEL:
            assert statement.sql is not None
            assert "FROM stop_events VERSION AS OF 0" in statement.sql
            assert "min(service_date)" not in statement.sql
            assert len(statement.adaptations) == 1
        else:
            assert statement.sql == suite.query_sql(statement.name)
            assert statement.adaptations == ()


def test_clickhouse_rewrites_and_marks_time_travel_not_applicable() -> None:
    statements = {s.name: s for s in dialect.statements("clickhouse", None)}
    for name in TIME_TRAVEL:
        assert statements[name].sql is None
        assert statements[name].reason
    for statement in statements.values():
        assert "percentile_disc" not in (statement.sql or "")
    gain = statements["q12_biggest_delay_gain_per_route"].sql or ""
    assert "lag(toNullable(delay_s))" in gain
    p50 = statements["q20_last_stop_vs_last_intermediate"].sql or ""
    assert (
        "arrayElement(arraySort(groupArray(t.delay_s - a.final_delay_s)), "
        "toUInt64(ceil(0.5 * count(t.delay_s - a.final_delay_s))))" in p50
    )


def test_unknown_engine_is_rejected() -> None:
    with pytest.raises(ValueError):
        dialect.adapt("oracle", "q01_on_time_by_mode_day", None)


@pytest.mark.parametrize("n", [1, 2, 3, 9, 10, 11, 20])
@pytest.mark.parametrize("p", [0.5, 0.9])
def test_percentile_definition_equals_percentile_disc(n: int, p: float) -> None:
    """The ClickHouse rewrite's definition (position ceil(p*n) of the sorted non-NULL values),
    checked against DuckDB's percentile_disc, including whole-number p*n and NULLs."""
    values = ", ".join(f"({v})" for v in [*range(n, 0, -1), "NULL"])
    disc, definition = duckdb.sql(
        f"SELECT percentile_disc({p}) WITHIN GROUP (ORDER BY x), "
        f"list_sort(list(x))[ceil({p} * count(x))::BIGINT] FROM (VALUES {values}) t(x)"
    ).fetchone() or (None, None)
    assert disc == definition


def test_runner_writes_answers_and_records_not_applicable(tmp_path: Path) -> None:
    executed: list[str] = []

    def execute(sql: str) -> pa.Table:
        executed.append(sql)
        return pa.table({"n": [1, 2]})

    stale = tmp_path / "q99_old.parquet"
    pq.write_table(pa.table({"n": [0]}), stale)
    record = run_suite("clickhouse", execute, None, tmp_path)
    assert not stale.exists()
    assert len(executed) == len(suite.query_names()) - len(TIME_TRAVEL)
    for name in TIME_TRAVEL:
        assert record["queries"][name]["applicable"] is False
        assert not (tmp_path / f"{name}.parquet").exists()
    first = record["queries"]["q01_on_time_by_mode_day"]
    assert first["rows"] == 2 and first["applicable"] is True
    assert pq.read_table(tmp_path / "q01_on_time_by_mode_day.parquet").num_rows == 2
    json.dumps(record)  # the record is the JSON report
