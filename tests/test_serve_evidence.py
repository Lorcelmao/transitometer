"""The app's evidence comes only from committed result files; absent files read as unmeasured."""

from __future__ import annotations

import json
from pathlib import Path

from transitometer.serve import evidence


def test_source_integrity_joins_the_three_committed_reports() -> None:
    result = evidence.source_integrity()
    assert result["available"] and result["ok"]
    assert {f["feed"] for f in result["feeds"]} == {
        "trip_updates.bus",
        "trip_updates.subway",
        "vehicle_positions.bus",
    }
    for feed in result["feeds"]:
        assert feed["rows_equal"] and feed["balanced"] and feed["read_back_equal"]
        assert feed["silver_rows"] == feed["archive_rows"]


def test_golden_parity_counts_tables_per_layer() -> None:
    result = evidence.golden_parity()
    layers = {layer["layer"]: layer for layer in result["layers"]}
    assert set(layers) == {"silver", "gold"}
    for layer in layers.values():
        assert layer["passed"] == layer["total"] == len(layer["tables"])
        assert all(t["rows"] is not None and t["rows"] > 0 for t in layer["tables"])


def test_missing_files_are_reported_as_not_measured(tmp_path: Path) -> None:
    assert evidence.source_integrity(tmp_path)["available"] is False
    assert evidence.golden_parity(tmp_path) == {"available": False, "ok": False, "layers": []}
    assert evidence.tests(tmp_path)["available"] is False


def test_a_failing_table_is_reported_as_failing(tmp_path: Path) -> None:
    body = {"tables": {"t": {"ok": False, "detail": "t: 2 rows differ (10 rows)"}}, "ok": False}
    (tmp_path / "validation-gold.json").write_text(json.dumps(body), encoding="utf-8")
    result = evidence.golden_parity(tmp_path)
    assert result["ok"] is False
    assert result["layers"][0]["passed"] == 0 and result["layers"][0]["total"] == 1
