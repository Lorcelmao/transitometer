"""The storage guard must stop engine starts above the block threshold (PROJECT_PLAN.md §1.3)."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tasks  # noqa: E402

from transitometer.ops.storage_check import (  # noqa: E402
    GB,
    StorageReport,
    Thresholds,
    build_report,
)


def fake_measure(logical_gb: float) -> Callable[[], tuple[StorageReport, Thresholds]]:
    def measure() -> tuple[StorageReport, Thresholds]:
        limits = Thresholds()
        return build_report({"Images": int(logical_gb * GB)}, None, limits), limits

    return measure


@pytest.fixture
def compose_calls(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Record commands instead of running docker."""
    calls: list[list[str]] = []

    def record(cmd: Sequence[str]) -> int:
        calls.append(list(cmd))
        return 0

    monkeypatch.setattr(tasks, "run", record)
    return calls


@pytest.mark.parametrize(("gb", "code"), [(10, 0), (31, 0), (36, 2)])
def test_storage_check_exit_codes(monkeypatch: pytest.MonkeyPatch, gb: float, code: int) -> None:
    monkeypatch.setattr(tasks, "measure_storage", fake_measure(gb))
    assert tasks.main(["storage-check"]) == code


def test_allow_peak_overrides_block(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks, "measure_storage", fake_measure(31))
    assert tasks.main(["storage-check", "--allow-peak"]) == 0


def test_up_refuses_to_start_when_blocked(
    monkeypatch: pytest.MonkeyPatch, compose_calls: list[list[str]]
) -> None:
    monkeypatch.setattr(tasks, "measure_storage", fake_measure(36))
    assert tasks.main(["up", "spark"]) == 2
    assert compose_calls == []


def test_up_starts_profile_when_within_budget(
    monkeypatch: pytest.MonkeyPatch, compose_calls: list[list[str]]
) -> None:
    monkeypatch.setattr(tasks, "measure_storage", fake_measure(10))
    assert tasks.main(["up", "spark"]) == 0
    assert compose_calls[-1][-4:] == ["--profile", "spark", "up", "-d"]


def test_up_kafka_uses_no_profile(
    monkeypatch: pytest.MonkeyPatch, compose_calls: list[list[str]]
) -> None:
    monkeypatch.setattr(tasks, "measure_storage", fake_measure(10))
    assert tasks.main(["up", "kafka"]) == 0
    assert "--profile" not in compose_calls[-1]
