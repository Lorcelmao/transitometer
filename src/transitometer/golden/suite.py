"""The frozen 25-query suite: the shared workload of the serving comparison.

Each query reads the golden table names (stop_events, headways, ...). The golden answers are the
suite run by DuckDB on the golden tables; every other engine must reproduce them. Answers are
sorted on all columns so they compare row by row.
"""

from __future__ import annotations

import hashlib
from importlib import resources
from pathlib import Path

import duckdb

from transitometer.golden.properties import register_tables


def query_names() -> list[str]:
    folder = resources.files("transitometer.golden").joinpath("queries")
    return sorted(p.name[: -len(".sql")] for p in folder.iterdir() if p.name.endswith(".sql"))


def query_sql(name: str) -> str:
    text = resources.files("transitometer.golden").joinpath("queries").joinpath(f"{name}.sql")
    return text.read_text("utf-8").strip().rstrip(";")


def _answer(con: duckdb.DuckDBPyConnection, name: str, out_dir: Path) -> Path:
    target = out_dir / f"{name}.parquet"
    con.execute(
        f"COPY (SELECT * FROM ({query_sql(name)}) ORDER BY ALL) "
        f"TO '{target.as_posix()}' (FORMAT parquet, COMPRESSION zstd)"
    )
    return target


def run_one(tables_dir: Path, name: str, out_dir: Path) -> Path:
    """One query over the tables in `tables_dir`; its sorted answer in `out_dir`."""
    with duckdb.connect() as con:
        register_tables(con, tables_dir)
        return _answer(con, name, out_dir)


def run(tables_dir: Path, out_dir: Path, threads: int = 8) -> dict[str, str]:
    """Run every query over the tables in `tables_dir`; write sorted answers; return checksums."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.parquet"):  # a renamed or removed query leaves no old answer
        stale.unlink()
    checksums = {}
    with duckdb.connect() as con:
        con.execute(f"SET threads = {threads}")
        register_tables(con, tables_dir)
        for name in query_names():
            target = _answer(con, name, out_dir)
            checksums[target.name] = hashlib.sha256(target.read_bytes()).hexdigest()
    return checksums
