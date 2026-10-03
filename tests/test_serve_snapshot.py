"""The snapshot only ever holds the output of a validated run, byte for byte and reproducibly."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import duckdb
import pytest

from transitometer.serve import kpis, snapshot

GOLDEN = kpis.REPO / "golden" / "tables"
POLICY = kpis.REPO / "golden" / "tolerance.json"
ORIGIN = snapshot.Origin("0123456789abcdef0123456789abcdef01234567", "2026-10-03")


def _rows(path: Path) -> int:
    row = duckdb.connect().execute(f"SELECT count(*) FROM '{path.as_posix()}'").fetchone()
    return int(row[0]) if row else 0


@pytest.fixture()
def run(tmp_path: Path) -> tuple[Path, Path]:
    """Exports and result files of a validated run, built from the frozen golden tables."""
    exports, results = tmp_path / "exports", tmp_path / "results"
    exports.mkdir()
    results.mkdir()
    rows = {}
    for name in kpis.APP_TABLES:
        target = exports / f"{name}.parquet"
        if (GOLDEN / f"{name}.parquet").exists():
            shutil.copyfile(GOLDEN / f"{name}.parquet", target)
        else:  # stop_names has no golden counterpart
            duckdb.connect().execute(
                f"COPY (SELECT 'bus' AS grp, 'S1' AS stop_id, 'Main St' AS stop_name) "
                f"TO '{target.as_posix()}' (FORMAT parquet)"
            )
        rows[name] = _rows(target)
    compared = {n: {"ok": True, "detail": f"{n}: equal ({r} rows)"} for n, r in rows.items()}
    del compared["stop_names"]
    reports = {
        "gold-kpis.json": {"prefix": "rt", "rows": rows},
        "validation-gold.json": {"layer": "gold", "tables": compared, "ok": True},
        "validation-silver.json": {
            "layer": "silver",
            "tables": {"stop_events": {"ok": True, "detail": "equal (5 rows)"}},
            "ok": True,
        },
        "replay-verification.json": {"ok": True},
        "test-summary.json": {"total": 2, "passed": 2, "failed": 0, "skipped": 0, "ok": True},
    }
    for name, body in reports.items():
        (results / name).write_text(json.dumps(body), encoding="utf-8")
    return exports, results


def test_app_tables_are_exactly_the_tables_the_queries_read() -> None:
    source = (kpis.REPO / "src" / "transitometer" / "serve" / "kpis.py").read_text(encoding="utf-8")
    assert set(re.findall(r"\.table\('(\w+)'\)", source)) == set(kpis.APP_TABLES)


def test_a_validated_run_becomes_a_byte_identical_snapshot(
    run: tuple[Path, Path], tmp_path: Path
) -> None:
    exports, results = run
    out = tmp_path / "snapshot"
    manifest = snapshot.build(exports, results, POLICY, out, ORIGIN)
    assert manifest["validation"] == {
        "ok": True,
        "silver": {"passed": 1, "total": 1},
        "gold": {"passed": len(kpis.APP_TABLES) - 1, "total": len(kpis.APP_TABLES) - 1},
    }
    assert manifest["service_dates"] == ["20260922", "20260923"]
    assert manifest["validated_commit"] == ORIGIN.commit
    for name, entry in manifest["tables"].items():
        assert (out / f"{name}.parquet").read_bytes() == (exports / f"{name}.parquet").read_bytes()
        assert entry["validated"] is (name != "stop_names")
    assert set(manifest["evidence"]) >= {"validation-gold.json", "tolerance.json"}
    first = {p.relative_to(out): p.read_bytes() for p in sorted(out.rglob("*")) if p.is_file()}
    snapshot.build(exports, results, POLICY, out, ORIGIN)
    second = {p.relative_to(out): p.read_bytes() for p in sorted(out.rglob("*")) if p.is_file()}
    assert first == second
    assert snapshot.load_manifest(out) == manifest


def test_the_snapshot_source_reads_the_snapshot_tables(
    run: tuple[Path, Path], tmp_path: Path
) -> None:
    out = tmp_path / "snapshot"
    snapshot.build(*run, POLICY, out, ORIGIN)
    src = kpis.Source("snapshot", str(out))
    with kpis.connect(src) as con:
        assert kpis.service_dates(con, src) == ["20260922", "20260923"]
    assert src.has("stop_names")


@pytest.mark.parametrize(
    ("report", "change", "reason"),
    [
        ("validation-gold.json", {"ok": False}, "gold validation did not pass"),
        ("replay-verification.json", {"ok": False}, "replay verification did not pass"),
    ],
)
def test_a_failed_check_refuses_and_writes_nothing(
    run: tuple[Path, Path], tmp_path: Path, report: str, change: dict[str, bool], reason: str
) -> None:
    exports, results = run
    body = json.loads((results / report).read_text(encoding="utf-8")) | change
    (results / report).write_text(json.dumps(body), encoding="utf-8")
    out = tmp_path / "snapshot"
    with pytest.raises(snapshot.SnapshotError, match=reason):
        snapshot.build(exports, results, POLICY, out, ORIGIN)
    assert not out.exists()


def test_exports_from_another_run_are_refused(run: tuple[Path, Path], tmp_path: Path) -> None:
    exports, results = run
    body = json.loads((results / "gold-kpis.json").read_text(encoding="utf-8"))
    body["rows"]["otp_summary"] += 1
    (results / "gold-kpis.json").write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(snapshot.SnapshotError, match="not from the validated run"):
        snapshot.build(exports, results, POLICY, tmp_path / "snapshot", ORIGIN)


def test_a_missing_export_names_the_command_that_writes_it(
    run: tuple[Path, Path], tmp_path: Path
) -> None:
    exports, results = run
    (exports / "stop_names.parquet").unlink()
    with pytest.raises(snapshot.SnapshotError, match="gold --export-only"):
        snapshot.build(exports, results, POLICY, tmp_path / "snapshot", ORIGIN)


def test_a_folder_without_a_snapshot_has_no_manifest(tmp_path: Path) -> None:
    assert snapshot.load_manifest(tmp_path) is None
