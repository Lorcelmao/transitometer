"""The SQL each Axis B arm runs for a frozen query, and the adaptations that took.

The suite text (golden/queries) is DuckDB SQL and stays frozen. An arm gets that text with the
fewest rewrites its engine needs; every rewrite is named, so the run report shows exactly what
each engine could not run verbatim (part of the operator-effort comparison).

The rewrites:
- time travel: q24/q25 read the first service day through a filter that stands in for a Delta
  version read. An arm that can read Delta versions passes the relation that reads version 0
  (the Axis B dataset commits one service day per version, oldest first); an arm that cannot
  gets None, and the query is not applicable.
- ClickHouse has no `percentile_disc(p) WITHIN GROUP (ORDER BY x)`; it is rewritten to the
  definition, the value at 1-based position ceil(p * n) of the n sorted non-NULL values.
  (`quantileExactLow` returns the next value when p * n is a whole number.)
- ClickHouse `lag(x)` returns the type's default (0) when there is no previous row, where SQL
  returns NULL; the NULL needs a Nullable argument, so `lag(x)` becomes `lag(toNullable(x))`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from transitometer.golden import suite

ENGINES = ("spark", "duckdb", "clickhouse")
TIME_TRAVEL_TABLE = "stop_events"

_COMMENT = re.compile(r"--[^\n]*")
_TABLE_REF = re.compile(r"\b(?:FROM|JOIN)\s+([a-z_][a-z0-9_]*)", re.IGNORECASE)
_FIRST_DAY = re.compile(
    r"FROM\s+stop_events\s+WHERE\s+service_date\s*=\s*"
    r"\(SELECT\s+min\(service_date\)\s+FROM\s+stop_events\)",
    re.IGNORECASE,
)
_PERCENTILE_DISC = re.compile(
    r"percentile_disc\(\s*([0-9.]+)\s*\)\s+WITHIN\s+GROUP\s*\(\s*ORDER\s+BY\s+([^()]+?)\s*\)",
    re.IGNORECASE,
)
_LAG = re.compile(r"\blag\(\s*([^(),]+?)\s*\)", re.IGNORECASE)


@dataclass(frozen=True)
class Statement:
    """What an arm runs for one query; `sql` is None when the query is not applicable."""

    name: str
    sql: str | None
    adaptations: tuple[str, ...]
    reason: str = ""


def tables() -> list[str]:
    """Every table the suite reads, in name order."""
    found: set[str] = set()
    for name in suite.query_names():
        code = _COMMENT.sub("", suite.query_sql(name))
        found.update(t.lower() for t in _TABLE_REF.findall(code))
    return sorted(found)


def _clickhouse_percentile(match: re.Match[str]) -> str:
    level, expr = match.group(1), match.group(2)
    return f"arrayElement(arraySort(groupArray({expr})), toUInt64(ceil({level} * count({expr}))))"


def adapt(engine: str, name: str, time_travel: str | None) -> Statement:
    """The statement `engine` runs for query `name`.

    `time_travel` is the engine's relation for version 0 of stop_events, or None when the arm
    cannot read Delta versions.
    """
    if engine not in ENGINES:
        raise ValueError(f"unknown engine {engine!r}")
    sql = suite.query_sql(name)
    applied: list[str] = []
    if _FIRST_DAY.search(sql):
        if time_travel is None:
            return Statement(name, None, (), "no Delta version read on this engine")
        sql = _FIRST_DAY.sub(lambda _: f"FROM {time_travel}", sql)
        applied.append("time travel: first service day read as Delta version 0")
    if engine == "clickhouse":
        sql, count = _PERCENTILE_DISC.subn(_clickhouse_percentile, sql)
        if count:
            applied.append(f"percentile_disc as its definition ({count}x)")
        sql, count = _LAG.subn(lambda m: f"lag(toNullable({m.group(1)}))", sql)
        if count:
            applied.append("lag over a Nullable argument (NULL when there is no previous row)")
    return Statement(name, sql, tuple(applied))


def statements(engine: str, time_travel: str | None) -> list[Statement]:
    return [adapt(engine, name, time_travel) for name in suite.query_names()]
