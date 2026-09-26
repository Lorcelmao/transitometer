"""DuckDB access to Delta tables (Delta extension pre-installed in the image, used offline).

Run as a module for the skeleton check: python -m transitometer.serve.lakehouse <delta path>
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import duckdb


def connect() -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB with the Delta extension loaded from the baked-in extension directory."""
    config: dict[str, Any] = {}
    ext_dir = os.environ.get("TRANSITOMETER_DUCKDB_EXT_DIR")
    if ext_dir:
        config["extension_directory"] = ext_dir
    con = duckdb.connect(config=config)
    con.execute("LOAD delta")
    return con


def _scan(table: str) -> str:
    return "delta_scan('" + table.replace("'", "''") + "')"


def summary(con: duckdb.DuckDBPyConnection, table: str) -> dict[str, Any]:
    rows, vehicles, first, last = con.execute(
        f"SELECT count(*), count(DISTINCT vehicle_id), min(feed_timestamp), max(feed_timestamp)"
        f" FROM {_scan(table)}"
    ).fetchone() or (0, 0, None, None)
    return {"rows": rows, "vehicles": vehicles, "first_feed_ts": first, "last_feed_ts": last}


def vehicles_per_minute(con: duckdb.DuckDBPyConnection, table: str) -> list[tuple[Any, int]]:
    """Distinct vehicles reporting in each minute of feed time."""
    return con.execute(
        f"""
        SELECT to_timestamp(feed_timestamp - feed_timestamp % 60) AS minute,
               count(DISTINCT vehicle_id) AS vehicles
        FROM {_scan(table)} GROUP BY 1 ORDER BY 1
        """
    ).fetchall()


def latest_positions(con: duckdb.DuckDBPyConnection, table: str) -> list[tuple[float, float]]:
    """Positions from the most recent snapshot (for a map)."""
    return con.execute(
        f"""
        SELECT latitude, longitude FROM {_scan(table)}
        WHERE feed_timestamp = (SELECT max(feed_timestamp) FROM {_scan(table)})
          AND latitude IS NOT NULL AND longitude IS NOT NULL
        """
    ).fetchall()


def main(argv: list[str] | None = None) -> int:
    table = (argv or sys.argv[1:])[0]
    with connect() as con:
        print(json.dumps(summary(con, table)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
