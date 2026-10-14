"""Axis B, B3: ClickHouse MergeTree tables loaded from the Axis B Delta tables, then the suite.

Runs on the host and talks to the server over HTTP (stdlib only). The server reads the Delta
tables in place with `deltaLakeLocal` (the lakehouse volume is mounted read-only under its
user_files). Loading:
- one MergeTree table per suite table in database `axis_b`, ordered by the table's golden key
  columns (golden/tolerance.json); a column the data never leaves NULL is declared non-Nullable;
- rows go in one service day at a time, as a daily load after each Delta commit would; each
  load is timed (freshness input for S10) and the row counts are checked against Delta.
Queries run with `join_use_nulls = 1` (SQL-standard NULLs for outer-join misses); the text
rewrites are in transitometer.axis_b.dialect. ClickHouse holds no Delta versions, so q24/q25
are not applicable.
"""

from __future__ import annotations

import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from transitometer.axis_b import dialect
from transitometer.axis_b.runner import run_suite

URL = "http://127.0.0.1:8123/"
DATABASE = "axis_b"
USER_FILES = "/var/lib/clickhouse/user_files"
QUERY_SETTINGS = {"join_use_nulls": "1"}
DAY = "service_date"


class ClickHouseError(RuntimeError):
    pass


def request(sql: str, **settings: str) -> bytes:
    """POST one statement; settings go in the URL. Raises ClickHouseError with the server text."""
    url = URL + ("?" + urllib.parse.urlencode(settings) if settings else "")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, sql.encode("utf-8"))) as resp:
            body: bytes = resp.read()
            return body
    except urllib.error.HTTPError as exc:
        raise ClickHouseError(exc.read().decode("utf-8", "replace").strip()) from exc


def rows(sql: str, **settings: str) -> list[dict[str, Any]]:
    text = request(f"{sql} FORMAT JSONEachRow", **settings).decode("utf-8")
    return [json.loads(line) for line in text.splitlines() if line]


def wait_ready(timeout_s: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            if urllib.request.urlopen(URL + "ping", timeout=5).read().strip() == b"Ok.":
                return
        except OSError:
            pass
        if time.monotonic() > deadline:
            raise ClickHouseError(f"ClickHouse not answering at {URL} after {timeout_s:.0f} s")
        time.sleep(1)


def delta_path(prefix: str, table: str) -> str:
    """The table's Axis B Delta folder as the server sees it (see layout.lakehouse_root)."""
    base = f"{USER_FILES}/lakehouse" + ("" if prefix == "rt" else f"/scratch/{prefix}")
    return f"{base}/axis_b/{table}"


def _quote(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


def column_types(source: str) -> list[tuple[str, str]]:
    """Delta columns with types; Nullable dropped where the data holds no NULLs."""
    described = [(r["name"], r["type"]) for r in rows(f"DESCRIBE {source}")]
    probes = ", ".join(f"countIf(isNull({_quote(n)})) AS {_quote(n)}" for n, _ in described)
    nulls = rows(f"SELECT {probes} FROM {source}")[0]
    out = []
    for name, kind in described:
        if kind.startswith("Nullable(") and int(nulls[name]) == 0:
            kind = kind[len("Nullable(") : -1]
        out.append((name, kind))
    return out


def load_table(prefix: str, table: str, keys: list[str]) -> dict[str, Any]:
    source = f"deltaLakeLocal('{delta_path(prefix, table)}')"
    columns = column_types(source)
    nullable_key = any(k == n and t.startswith("Nullable(") for k in keys for n, t in columns)
    target = f"{DATABASE}.{_quote(table)}"
    request(f"DROP TABLE IF EXISTS {target}")
    request(
        f"CREATE TABLE {target} ("
        + ", ".join(f"{_quote(n)} {t}" for n, t in columns)
        + ") ENGINE = MergeTree ORDER BY ("
        + ", ".join(_quote(k) for k in keys)
        + ")"
        + (" SETTINGS allow_nullable_key = 1" if nullable_key else "")
    )
    names = [n for n, _ in columns]
    days = (
        [r["d"] for r in rows(f"SELECT DISTINCT {DAY} AS d FROM {source} ORDER BY d")]
        if DAY in names
        else [None]
    )
    loads = []
    for day in days:
        where = "" if day is None else f" WHERE {DAY} = '{day}'"
        started = time.perf_counter()
        request(f"INSERT INTO {target} SELECT * FROM {source}{where}")
        loads.append({"service_date": day, "seconds": round(time.perf_counter() - started, 3)})
    delta_rows = int(rows(f"SELECT count() AS n FROM {source}")[0]["n"])
    loaded = int(rows(f"SELECT count() AS n FROM {target}")[0]["n"])
    return {
        "source": delta_path(prefix, table),
        "delta_rows": delta_rows,
        "rows": loaded,
        "loads": loads,
        "non_nullable_columns": sum(not t.startswith("Nullable(") for _, t in columns),
        "columns": len(columns),
        "ok": loaded == delta_rows,
    }


def load(prefix: str, policy_file: Path) -> dict[str, Any]:
    keys = {t: v["keys"] for t, v in json.loads(policy_file.read_text("utf-8"))["tables"].items()}
    request(f"DROP DATABASE IF EXISTS {DATABASE}")
    request(f"CREATE DATABASE {DATABASE}")
    tables = {t: load_table(prefix, t, keys[t]) for t in dialect.tables()}
    return {
        "version": request("SELECT version()").decode().strip(),
        "database": DATABASE,
        "tables": tables,
        "ok": all(t["ok"] for t in tables.values()),
    }


def run(out_dir: Path, threads: int = 8) -> dict[str, Any]:
    settings = {**QUERY_SETTINGS, "database": DATABASE, "max_threads": str(threads)}

    def execute(sql: str) -> pa.Table:
        return pq.read_table(io.BytesIO(request(f"{sql}\nFORMAT Parquet", **settings)))

    record = run_suite("clickhouse", execute, None, out_dir)
    record.update(
        {
            "version": request("SELECT version()").decode().strip(),
            "threads": threads,
            "settings": QUERY_SETTINGS,
        }
    )
    return record
