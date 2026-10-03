"""Validated snapshot of the Spark Gold tables the apps read, for hosting without the pipeline.

`python tasks.py snapshot` copies the app tables (kpis.APP_TABLES) from the host exports of the
kept replay into showcase/data/, with the evidence files of the run and a manifest:

  showcase/data/<table>.parquet       byte copies of the exported Gold tables
  showcase/data/evidence/*.json       the result files that prove the run (and the tolerance policy)
  showcase/data/manifest.json         commit and date of the validated run, rows and SHA-256 per
                                      file, validation summary

It refuses unless the Silver and Gold comparisons with golden passed, the replay verification
passed, and every exported table has exactly the row count the validated Gold run reported, so a
snapshot can only ever hold the output of a validated run. The same inputs give a byte-identical
snapshot.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from transitometer.serve.kpis import APP_TABLES

SCHEMA = "transitometer.snapshot/1"
# Result files copied as evidence; test-summary is written by `tasks.py test --record`.
EVIDENCE = (
    "replay-report.json",
    "replay-verification.json",
    "silver-ingest.json",
    "validation-silver.json",
    "validation-gold.json",
    "gold-kpis.json",
    "test-summary.json",
)
POLICY = "tolerance.json"


class SnapshotError(Exception):
    """The inputs do not prove a validated run; nothing was written."""


@dataclass(frozen=True)
class Origin:
    """The commit that recorded the validated run (the last change to validation-gold.json)."""

    commit: str
    date: str  # YYYY-MM-DD


def _json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SnapshotError(f"missing {path.name}: run the pipeline step that writes it")
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _scan(path: Path) -> str:
    return "'" + str(path).replace("\\", "/").replace("'", "''") + "'"


def _rows(path: Path) -> int:
    with duckdb.connect() as con:
        row = con.execute(f"SELECT count(*) FROM {_scan(path)}").fetchone()
    return int(row[0]) if row else 0


def _validation(results: Path) -> dict[str, dict[str, int]]:
    """Per layer: tables equal to golden / compared; refuses unless every table is equal."""
    summary = {}
    for layer in ("silver", "gold"):
        report = _json(results / f"validation-{layer}.json")
        tables = report["tables"]
        passed = sum(bool(t["ok"]) for t in tables.values())
        if not report["ok"] or passed != len(tables):
            raise SnapshotError(f"{layer} validation did not pass ({passed}/{len(tables)} equal)")
        summary[layer] = {"passed": passed, "total": len(tables)}
    if not _json(results / "replay-verification.json").get("ok"):
        raise SnapshotError("replay verification did not pass")
    return summary


def build(exports: Path, results: Path, policy: Path, out: Path, origin: Origin) -> dict[str, Any]:
    """Write the snapshot into `out` and return its manifest; raise SnapshotError instead."""
    validation = _validation(results)
    reported = _json(results / "gold-kpis.json")["rows"]
    compared = _json(results / "validation-gold.json")["tables"]
    tables: dict[str, dict[str, Any]] = {}
    for name in APP_TABLES:
        source = exports / f"{name}.parquet"
        if not source.exists():
            raise SnapshotError(
                f"{name} is not exported; run `python tasks.py gold --export-only` (needs Docker)"
            )
        rows = _rows(source)
        if rows != reported.get(name):
            raise SnapshotError(
                f"{name}: {rows} exported rows, but the validated Gold run reported "
                f"{reported.get(name)}; the exports are not from the validated run"
            )
        tables[name] = {"rows": rows, "validated": name in compared}

    evidence_dir = out / "evidence"
    if out.exists():
        shutil.rmtree(out)  # the snapshot is fully derived; never keep stale tables
    evidence_dir.mkdir(parents=True)
    for name, entry in tables.items():
        target = out / f"{name}.parquet"
        shutil.copyfile(exports / f"{name}.parquet", target)
        entry.update(bytes=target.stat().st_size, sha256=_sha256(target))
    evidence = {}
    for name in EVIDENCE:
        source = results / name
        if source.exists():  # test-summary is optional: the app shows "not yet measured"
            shutil.copyfile(source, evidence_dir / name)
            evidence[name] = _sha256(evidence_dir / name)
    shutil.copyfile(policy, evidence_dir / POLICY)
    evidence[POLICY] = _sha256(evidence_dir / POLICY)

    with duckdb.connect() as con:
        sql = f"SELECT DISTINCT service_date FROM {_scan(out / 'otp_summary.parquet')} ORDER BY 1"
        days = [row[0] for row in con.execute(sql).fetchall()]
    manifest = {
        "schema": SCHEMA,
        "source": {"kind": "spark-gold", "prefix": "rt", "layer": "gold"},
        "validated_commit": origin.commit,
        "validated_on": origin.date,
        "service_dates": days,
        "validation": {"ok": True, **validation},
        "tables": tables,
        "evidence": evidence,
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return manifest


def load_manifest(folder: Path) -> dict[str, Any] | None:
    """The snapshot's manifest, or None when the folder holds no snapshot."""
    path = folder / "manifest.json"
    if not path.exists():
        return None
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data
