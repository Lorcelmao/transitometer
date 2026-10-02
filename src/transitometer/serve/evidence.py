"""Verified pipeline evidence for the app, read only from committed results/*.json files.

Nothing here computes or assumes a number: every figure comes from a result file written by a
pipeline run, and a missing file yields `available: False` (shown as "not yet measured").

  source integrity  replay-report, replay-verification, silver-ingest: the data entering the
                    pipeline is the archive, complete and unaltered
  golden parity     validation-silver, validation-gold: Spark equals the independent DuckDB
                    reference under golden/tolerance.json
  tests             test-summary (when recorded): automated test results
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
RESULTS = REPO / "results"
ROW_COUNT = re.compile(r"\((\d+) rows\)")


def _load(folder: Path, name: str) -> dict[str, Any] | None:
    path = folder / f"{name}.json"
    if not path.exists():
        return None
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def source_integrity(folder: Path = RESULTS) -> dict[str, Any]:
    """Per feed: archive -> Kafka -> Silver counts and checks, joined from three result files."""
    replay = _load(folder, "replay-report")
    verification = _load(folder, "replay-verification")
    silver = _load(folder, "silver-ingest")
    files = ["replay-report.json", "replay-verification.json", "silver-ingest.json"]
    if not (replay and verification and silver):
        return {"available": False, "files": files}
    ingest = {f["feed"]: f for f in silver["feeds"]}
    checks = verification["feeds"]
    feeds = []
    for row in replay["feeds"]:
        name = row["feed"]
        check, kept = checks[name], ingest[name]
        feeds.append(
            {
                "feed": name,
                "snapshots": row["snapshots"],
                "archive_rows": row["rows"],
                "messages": row["messages"],
                "all_acknowledged": row["acknowledged"] == row["messages"],
                "read_back_equal": check["acknowledged_equal"] and check["consumed_equal"],
                "markers_equal": check["markers_equal"],
                "timestamps_backwards": check["timestamps_backwards"],
                "fidelity_sampled": check["fidelity_sampled"],
                "fidelity_mismatched": len(check["fidelity_mismatched"]),
                "silver_rows": kept["rows_total"],
                "rows_equal": kept["rows_total"] == row["rows"],
                "duplicates": kept["duplicates_dropped"],
                "late": kept["late_dropped"],
                "dead_lettered": kept["dead_lettered"],
                "balanced": kept["balanced"],
            }
        )
    ok = verification["ok"] and all(
        f["all_acknowledged"] and f["rows_equal"] and f["balanced"] for f in feeds
    )
    return {"available": True, "ok": ok, "days": replay["days"], "feeds": feeds, "files": files}


def golden_parity(folder: Path = RESULTS) -> dict[str, Any]:
    """Per layer and table: equal to the golden reference or not, with the rows compared."""
    layers = []
    for layer in ("silver", "gold"):
        data = _load(folder, f"validation-{layer}")
        if data is None:
            continue
        tables = []
        for table, result in data["tables"].items():
            rows = ROW_COUNT.search(result["detail"])
            tables.append(
                {"table": table, "ok": result["ok"], "rows": int(rows.group(1)) if rows else None}
            )
        layers.append(
            {
                "layer": layer,
                "passed": sum(t["ok"] for t in tables),
                "total": len(tables),
                "tables": tables,
                "file": f"validation-{layer}.json",
            }
        )
    return {
        "available": bool(layers),
        "ok": bool(layers) and all(layer["passed"] == layer["total"] for layer in layers),
        "layers": layers,
    }


def tests(folder: Path = RESULTS) -> dict[str, Any]:
    """Automated test results, when a run recorded them (otherwise: not yet measured)."""
    data = _load(folder, "test-summary")
    if data is None:
        return {"available": False, "file": "test-summary.json"}
    return {"available": True, "file": "test-summary.json", **data}
