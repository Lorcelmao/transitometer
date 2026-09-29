"""The correctness harness: table comparison, invariants and the frozen query suite."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pytest

from test_golden_kpis import PARAMS, build_landing
from transitometer.golden import harness, properties, runner, suite
from transitometer.golden.compare import Policy, compare, compare_ordered

REPO_GOLDEN = Path(__file__).resolve().parents[1] / "golden"


def _table(**columns: list[object]) -> pa.Table:
    return pa.table(columns)


def test_identical_tables_match() -> None:
    t = _table(k=[1, 2], v=[10, 20], f=[0.5, 0.25])
    assert compare("t", t, t, ["k"], 1e-4).ok


def test_float_tolerance_is_absolute_and_inclusive() -> None:
    expected = _table(k=[1, 2], f=[0.5, 0.5])
    within = _table(k=[1, 2], f=[0.50005, 0.4999])
    beyond = _table(k=[1, 2], f=[0.5, 0.5002])
    assert compare("t", expected, within, ["k"], 1e-4).ok
    diff = compare("t", expected, beyond, ["k"], 1e-4)
    assert diff.mismatches == {"f": 1} and diff.examples[0]["k"] == 2


def test_one_rounding_step_is_within_a_tolerance_of_one_step() -> None:
    # 0.8766 - 0.8765 is 1.00000000000001e-4 in binary floating point.
    expected = _table(k=[1, 2], f=[0.8766, 0.5])
    assert compare("t", expected, _table(k=[1, 2], f=[0.8765, 0.5001]), ["k"], 1e-4).ok
    assert not compare("t", expected, _table(k=[1, 2], f=[0.8764, 0.5]), ["k"], 1e-4).ok


def test_integers_and_strings_are_exact() -> None:
    expected = _table(k=["a", "b"], n=[10, 20], s=["x", "y"])
    actual = _table(k=["a", "b"], n=[10, 21], s=["x", "z"])
    assert compare("t", expected, actual, ["k"], 1.0).mismatches == {"n": 1, "s": 1}


def test_missing_extra_and_duplicate_rows_are_reported() -> None:
    expected = _table(k=[1, 2, 3], v=[1, 2, 3])
    actual = _table(k=[1, 3, 4, 4], v=[1, 3, 4, 4])
    diff = compare("t", expected, actual, ["k"], 0.0)
    assert (diff.missing_rows, diff.extra_rows, diff.duplicate_keys) == (1, 2, 1)
    assert not diff.ok


def test_null_against_value_differs() -> None:
    expected = _table(k=[1, 2], f=pa.array([None, 1.0], pa.float64()))
    assert compare("t", expected, expected, ["k"], 0.0).ok
    actual = _table(k=[1, 2], f=pa.array([0.0, None], pa.float64()))
    assert compare("t", expected, actual, ["k"], 1.0).mismatches == {"f": 2}


def test_missing_column_fails_extra_column_is_tolerated() -> None:
    expected = _table(k=[1], v=[1])
    assert not compare("t", expected, _table(k=[1]), ["k"], 0.0).ok
    assert compare("t", expected, _table(k=[1], v=[1], extra=[9]), ["k"], 0.0).ok


def test_query_answers_compare_in_order() -> None:
    expected = _table(route=["A", "B"], share=[0.5, 0.6])
    assert compare_ordered("q", expected, expected, 1e-4).ok
    # An engine may return rows in another order or sort NULLs first: rows are paired after sorting.
    with_null = _table(route=["A", "B", None], share=[0.5, 0.6, None])
    reordered = _table(route=[None, "B", "A"], share=[None, 0.6, 0.5])
    assert compare_ordered("q", with_null, reordered, 1e-4).ok
    assert not compare_ordered("q", expected, _table(route=["A", "B"], share=[0.5, 0.7]), 1e-4).ok
    assert not compare_ordered("q", expected, _table(route=["A"], share=[0.5]), 1e-4).ok


def test_policy_covers_every_exported_table() -> None:
    policy = Policy.load(REPO_GOLDEN / "tolerance.json")
    assert set(policy.tables) == set(runner.EXPORTED_TABLES)
    assert policy.tolerance("delay_attribution_summary", "mean_final_delay_s") == 0.1
    assert policy.tolerance("stop_events", "anything") == policy.float_abs == 1e-4


def test_suite_has_the_frozen_25_queries() -> None:
    names = suite.query_names()
    assert len(names) == 25 and names[0].startswith("q01_") and names[-1].startswith("q25_")


@pytest.fixture(scope="module")
def golden_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("harness")
    config = build_landing(root / "landing")
    return runner.run(
        config, root / "landing", root / "out", params=PARAMS, memory_limit="1GB"
    ).out_dir


@pytest.fixture(scope="module")
def repo_golden(golden_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A repo golden/ folder frozen from the hand-built day."""
    repo = tmp_path_factory.mktemp("repo_golden")
    shutil.copyfile(REPO_GOLDEN / "tolerance.json", repo / "tolerance.json")
    suite.run(golden_dir, repo / "queries", threads=2)
    return repo


def test_invariants_hold_on_the_hand_built_day(golden_dir: Path) -> None:
    assert properties.check(golden_dir) == {name: 0 for name in properties.CHECKS}


def test_suite_answers_are_deterministic(golden_dir: Path, tmp_path: Path) -> None:
    assert suite.run(golden_dir, tmp_path / "a", threads=1) == suite.run(
        golden_dir, tmp_path / "b", threads=4
    )


def test_harness_accepts_an_exact_copy(golden_dir: Path, repo_golden: Path, tmp_path: Path) -> None:
    copy = tmp_path / "engine"
    shutil.copytree(golden_dir, copy)
    report = harness.run(golden_dir, repo_golden, copy)
    assert report.failures == 0, "\n".join(report.lines)


def test_harness_rejects_a_corrupted_result(
    golden_dir: Path, repo_golden: Path, tmp_path: Path
) -> None:
    engine = tmp_path / "engine"
    shutil.copytree(golden_dir, engine)
    events = pq.read_table(engine / "stop_events.parquet")
    # One on-time event turns 1,000 s late: its value, an invariant and q01's share all change.
    delays = events["delay_s"].to_pylist()
    victim = next(i for i, d in enumerate(delays) if -60 <= d <= 300)
    bump = [1000 if i == victim else 0 for i in range(events.num_rows)]
    shifted = pc.add(events["delay_s"], pa.array(bump, pa.int64()))
    pq.write_table(
        events.set_column(events.column_names.index("delay_s"), "delay_s", shifted),
        engine / "stop_events.parquet",
    )
    report = harness.run(golden_dir, repo_golden, engine)
    failed = [line for line in report.lines if "FAIL" in line]
    assert any(
        line.startswith("  FAIL  stop_events:") and "delay_s: 1 differ" in line for line in failed
    )
    assert any("delay_is_observed_minus_scheduled" in line for line in failed)
    assert any(line.startswith("  FAIL  query q01_") for line in failed)


def test_invariants_count_nulls_as_violations(golden_dir: Path, tmp_path: Path) -> None:
    engine = tmp_path / "engine"
    shutil.copytree(golden_dir, engine)
    events = pq.read_table(engine / "stop_events.parquet")
    nulled = pa.array([None] + events["delay_s"].to_pylist()[1:], pa.int64())
    pq.write_table(
        events.set_column(events.column_names.index("delay_s"), "delay_s", nulled),
        engine / "stop_events.parquet",
    )
    result = properties.check(engine)
    assert result["delay_is_observed_minus_scheduled"] == 1
    assert result["stop_events_near_timetable"] == 1


def test_a_missing_table_fails_its_items_without_aborting(
    golden_dir: Path, repo_golden: Path, tmp_path: Path
) -> None:
    engine = tmp_path / "engine"
    shutil.copytree(golden_dir, engine)
    (engine / "trip_delivery.parquet").unlink()
    report = harness.run(golden_dir, repo_golden, engine)
    failed = [line for line in report.lines if "FAIL" in line]
    assert any(line.startswith("  FAIL  trip_delivery:") for line in failed)
    assert any("property delivery_summary_matches_trips: error" in line for line in failed)
    assert any(line.startswith("  FAIL  query q05_") for line in failed)
    # the other checks still ran and passed
    assert any(line.startswith("  ok    stop_events:") for line in report.lines)


def test_checksum_mode_verifies_outputs_copies_and_answers(
    golden_dir: Path, repo_golden: Path
) -> None:
    result = runner.GoldenResult(out_dir=golden_dir)
    result.checksums = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in golden_dir.glob("*.parquet")
    }
    runner.write_repo_artifacts(result, repo_golden)
    (repo_golden / "queries" / "checksums.json").write_text(
        json.dumps(suite.run(golden_dir, repo_golden / "queries")), encoding="utf-8"
    )
    assert harness.run(golden_dir, repo_golden).failures == 0
    copy = repo_golden / "tables" / "route_scorecard.parquet"
    copy.write_bytes(copy.read_bytes() + b"x")
    report = harness.run(golden_dir, repo_golden)
    assert [line for line in report.lines if "FAIL" in line] == [
        "  FAIL  checksum tables/route_scorecard.parquet"
    ]
