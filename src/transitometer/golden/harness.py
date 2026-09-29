"""Correctness harness: check a set of result tables against the frozen golden reference.

Four kinds of check, each reported per item:
  checksums   (golden only) every golden file, committed table copy and frozen query answer
              still matches its committed checksum
  tables      (another engine) every golden table is reproduced within the tolerance policy
  properties  every invariant in properties.CHECKS holds (0 violating rows)
  queries     the 25-query suite over the tables reproduces the frozen answers
An error in one item (a missing table, an incompatible column type) fails that item only.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pyarrow.parquet as pq

from transitometer.golden import properties, suite
from transitometer.golden.compare import Policy, compare_ordered, compare_table
from transitometer.golden.runner import LARGE_TABLES


@dataclass
class Report:
    lines: list[str] = field(default_factory=list)
    failures: int = 0

    def add(self, ok: bool, line: str) -> None:
        self.lines.append(("  ok    " if ok else "  FAIL  ") + line)
        self.failures += 0 if ok else 1

    def guarded(self, label: str, check: Callable[[], None]) -> None:
        """Run one check; an exception fails it with its message instead of aborting."""
        try:
            check()
        except Exception as exc:  # noqa: BLE001 - reported as a failed item
            self.add(False, f"{label}: error {type(exc).__name__}: {exc}")


def _verify_files(folder: Path, expected: dict[str, str], label: str, report: Report) -> None:
    for name, digest in sorted(expected.items()):
        path = folder / name
        actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "missing"
        report.add(actual == digest, f"checksum {label}{name}")


def verify_checksums(golden_dir: Path, repo_golden: Path, report: Report) -> None:
    """Data-folder outputs, their committed copies, and the frozen query answers."""
    tables: dict[str, str] = json.loads((repo_golden / "checksums.json").read_text("utf-8"))
    _verify_files(golden_dir, tables, "", report)
    copies = {p.name for p in (repo_golden / "tables").glob("*.parquet")}
    _verify_files(repo_golden / "tables", {n: tables[n] for n in copies}, "tables/", report)
    report.add(
        copies == {n for n in tables if n.split(".")[0] not in LARGE_TABLES},
        "committed table copies: exactly the non-large tables",
    )
    answers = json.loads((repo_golden / "queries" / "checksums.json").read_text("utf-8"))
    _verify_files(repo_golden / "queries", answers, "queries/", report)


def verify_tables(golden_dir: Path, actual_dir: Path, policy: Policy, report: Report) -> None:
    for name in sorted(policy.tables):

        def one(name: str = name) -> None:
            diff = compare_table(name, golden_dir, actual_dir, policy)
            report.add(diff.ok, diff.describe())
            for example in diff.examples[:3]:
                report.lines.append(f"          e.g. {example}")

        report.guarded(name, one)


def verify_properties(tables_dir: Path, report: Report) -> None:
    for name, outcome in properties.check(tables_dir).items():
        if isinstance(outcome, int):
            report.add(outcome == 0, f"property {name}: {outcome} violating rows")
        else:
            report.add(False, f"property {name}: error {outcome}")


def verify_queries(tables_dir: Path, answers_dir: Path, policy: Policy, report: Report) -> None:
    """The suite run by DuckDB over the given tables. (Running it natively in Spark SQL or
    ClickHouse is the serving comparison's job; their answers are compared the same way.)"""
    with tempfile.TemporaryDirectory() as tmp:
        for name in suite.query_names():

            def one(name: str = name) -> None:
                answer = suite.run_one(tables_dir, name, Path(tmp))
                expected = pq.read_table(answers_dir / f"{name}.parquet")
                diff = compare_ordered(name, expected, pq.read_table(answer), policy.float_abs)
                report.add(diff.ok, f"query {diff.describe()}")

            report.guarded(f"query {name}", one)


def run(
    golden_dir: Path,
    repo_golden: Path,
    actual_dir: Path | None = None,
) -> Report:
    """Check the golden output itself (actual_dir None) or another engine's tables."""
    policy = Policy.load(repo_golden / "tolerance.json")
    report = Report()
    tables = golden_dir if actual_dir is None else actual_dir
    if actual_dir is None:
        report.guarded("checksums", lambda: verify_checksums(golden_dir, repo_golden, report))
    else:
        verify_tables(golden_dir, actual_dir, policy, report)
    verify_properties(tables, report)
    verify_queries(tables, repo_golden / "queries", policy, report)
    return report
