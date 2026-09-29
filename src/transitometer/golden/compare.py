"""Compare an engine's result tables with the golden ones under the declared tolerance policy.

Used for every later stage (Spark, Flink, ClickHouse): point it at the engine's exported Parquet
tables and the golden directory. Keyed tables are matched on their key columns; query answers
are matched row by row in sorted order.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.compute
import pyarrow.parquet as pq

FLOAT_TYPES = ("DOUBLE", "FLOAT", "REAL", "DECIMAL")
EXAMPLES = 5
# A tolerance equal to a rounding step must accept a one-step difference: 0.8766 - 0.8765 is
# 1.00000000000001e-4 in binary floating point.
FLOAT_EPSILON = 1e-9


@dataclass
class TableDiff:
    """Differences between an expected (golden) and an actual table."""

    name: str
    expected_rows: int = 0
    actual_rows: int = 0
    missing_columns: list[str] = field(default_factory=list)
    extra_columns: list[str] = field(default_factory=list)
    duplicate_keys: int = 0
    missing_rows: int = 0
    extra_rows: int = 0
    mismatches: dict[str, int] = field(default_factory=dict)
    examples: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (
            self.missing_columns
            or self.duplicate_keys
            or self.missing_rows
            or self.extra_rows
            or self.mismatches
        )

    def describe(self) -> str:
        extra = f"; extra columns ignored: {self.extra_columns}" if self.extra_columns else ""
        if self.ok:
            return f"{self.name}: OK ({self.expected_rows} rows{extra})"
        parts = [
            f"{label} {value}"
            for label, value in (
                ("missing columns", self.missing_columns),
                ("duplicate keys", self.duplicate_keys),
                ("missing rows", self.missing_rows),
                ("extra rows", self.extra_rows),
            )
            if value
        ]
        parts += [f"{column}: {count} differ" for column, count in self.mismatches.items()]
        return f"{self.name}: FAIL ({'; '.join(parts)}{extra})"


@dataclass(frozen=True)
class Policy:
    float_abs: float
    tables: dict[str, dict[str, Any]]

    @classmethod
    def load(cls, path: Path) -> Policy:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(float(raw["float_abs"]), raw["tables"])

    def keys(self, table: str) -> list[str]:
        keys: list[str] = self.tables[table]["keys"]
        return keys

    def tolerance(self, table: str, column: str) -> float:
        overrides = self.tables.get(table, {}).get("float_abs", {})
        return float(overrides.get(column, self.float_abs))


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def compare(
    name: str,
    expected: pa.Table,
    actual: pa.Table,
    keys: list[str],
    tolerance: dict[str, float] | float,
) -> TableDiff:
    """Match rows on `keys`; compare every other column (floats within their tolerance)."""
    diff = TableDiff(name, expected.num_rows, actual.num_rows)
    diff.missing_columns = [c for c in expected.column_names if c not in actual.column_names]
    diff.extra_columns = [c for c in actual.column_names if c not in expected.column_names]
    if diff.missing_columns:
        return diff
    with duckdb.connect() as con:
        con.register("e", expected)
        con.register("a", actual.select(expected.column_names))
        key_list = ", ".join(_quote(k) for k in keys)
        for side in ("e", "a"):
            dup = con.execute(
                f"SELECT count(*) FROM (SELECT {key_list} FROM {side} "
                "GROUP BY ALL HAVING count(*) > 1)"
            ).fetchone()
            diff.duplicate_keys += int(dup[0]) if dup else 0
        join = " AND ".join(f"e.{_quote(k)} IS NOT DISTINCT FROM a.{_quote(k)}" for k in keys)
        counts = con.execute(
            f"SELECT count(*) FILTER (WHERE a._a IS NULL), count(*) FILTER (WHERE e._e IS NULL) "
            "FROM (SELECT *, true AS _e FROM e) e "
            f"FULL JOIN (SELECT *, true AS _a FROM a) a ON {join}"
        ).fetchone()
        diff.missing_rows, diff.extra_rows = (int(counts[0]), int(counts[1])) if counts else (0, 0)
        types = dict(con.execute("SELECT column_name, column_type FROM (DESCRIBE e)").fetchall())
        diff.mismatches, diff.examples = _mismatches(con, expected, keys, types, tolerance)
    return diff


def _mismatches(
    con: duckdb.DuckDBPyConnection,
    expected: pa.Table,
    keys: list[str],
    types: dict[str, str],
    tolerance: dict[str, float] | float,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Per non-key column: rows present on both sides whose values differ beyond tolerance."""
    join = " AND ".join(f"e.{_quote(k)} IS NOT DISTINCT FROM a.{_quote(k)}" for k in keys)
    counts: dict[str, int] = {}
    examples: list[dict[str, Any]] = []
    for column in expected.column_names:
        if column in keys:
            continue
        e_col, a_col = f"e.{_quote(column)}", f"a.{_quote(column)}"
        if str(types[column]).upper().startswith(FLOAT_TYPES):
            tol = float(tolerance.get(column, 0.0) if isinstance(tolerance, dict) else tolerance)
            differs = (
                f"(({e_col} IS NULL) <> ({a_col} IS NULL) "
                f"OR abs({e_col} - {a_col}) > {tol + FLOAT_EPSILON})"
            )
        else:
            differs = f"{e_col} IS DISTINCT FROM {a_col}"
        where = f"FROM e JOIN a ON {join} WHERE {differs}"
        row = con.execute(f"SELECT count(*) {where}").fetchone()
        count = int(row[0]) if row else 0
        if count:
            counts[column] = count
            key_cols = ", ".join(f"e.{_quote(k)}" for k in keys)
            sample = con.execute(
                f"SELECT {key_cols}, {e_col} AS expected, {a_col} AS actual {where} "
                f"ORDER BY ALL LIMIT {EXAMPLES}"
            )
            names = [d[0] for d in sample.description]
            examples += [
                {"column": column, **dict(zip(names, r, strict=True))} for r in sample.fetchall()
            ]
    return counts, examples


def compare_table(name: str, golden_dir: Path, actual_dir: Path, policy: Policy) -> TableDiff:
    expected = pq.read_table(golden_dir / f"{name}.parquet")
    actual_path = actual_dir / f"{name}.parquet"
    if not actual_path.exists():
        return TableDiff(name, expected.num_rows, 0, missing_columns=["<table missing>"])
    columns = {c: policy.tolerance(name, c) for c in expected.column_names}
    return compare(name, expected, pq.read_table(actual_path), policy.keys(name), columns)


def _sorted(table: pa.Table) -> pa.Table:
    """Sorted on all columns with NULLs last, whatever order the producer used."""
    keys = [(name, "ascending", "at_end") for name in table.column_names]
    order = pa.compute.sort_indices(table, sort_keys=keys)
    ordered = table.take(order)
    return ordered.append_column("_row", pa.array(range(ordered.num_rows), pa.int64()))


def compare_ordered(name: str, expected: pa.Table, actual: pa.Table, float_abs: float) -> TableDiff:
    """Query answers: both sides sorted on all columns, then compared row by row."""
    if [c for c in expected.column_names if c not in actual.column_names]:
        return compare(name, expected, actual, expected.column_names[:1], float_abs)
    return compare(
        name, _sorted(expected), _sorted(actual.select(expected.column_names)), ["_row"], float_abs
    )
