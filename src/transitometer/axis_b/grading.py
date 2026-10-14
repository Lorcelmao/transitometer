"""Grade an Axis B arm's answers against the frozen golden answers (golden/queries)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from transitometer.golden import compare


def grade(
    record: dict[str, Any], answers: Path, repo_golden: Path, golden_tables: Path
) -> dict[str, Any]:
    """Per query of a run record: equal yes/no, detail, examples, rounding ties, adaptations.

    `golden_tables` holds the golden tables the answers stem from (for the tie check).
    """
    policy = compare.Policy.load(repo_golden / "tolerance.json")
    queries: dict[str, dict[str, Any]] = {}
    for name, info in record["queries"].items():
        if not info["applicable"]:
            queries[name] = {"applicable": False, "reason": info["reason"]}
            continue
        expected = pq.read_table(repo_golden / "queries" / f"{name}.parquet")
        actual = pq.read_table(answers / f"{name}.parquet")
        diff = compare.compare_query(name, expected, actual, policy, golden_tables)
        queries[name] = {
            "applicable": True,
            "ok": diff.ok,
            "detail": diff.describe(),
            "examples": diff.examples[:5],
            "rounding_ties": diff.ties,
            "adaptations": info["adaptations"],
        }
    applicable = [q for q in queries.values() if q["applicable"]]
    return {
        "equal": sum(1 for q in applicable if q["ok"]),
        "applicable": len(applicable),
        "ok": all(q["ok"] for q in applicable),
        "queries": queries,
    }
