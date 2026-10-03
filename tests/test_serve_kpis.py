"""The app's KPI queries, run against the frozen golden tables (the same SQL serves Gold Delta)."""

from __future__ import annotations

import pytest

from transitometer.serve import kpis

SRC = kpis.Source("golden", str(kpis.REPO / "golden" / "tables"))


@pytest.fixture(scope="module")
def con():  # type: ignore[no-untyped-def]
    connection = kpis.connect(SRC)
    yield connection
    connection.close()


def test_service_dates_are_the_golden_window(con) -> None:  # type: ignore[no-untyped-def]
    assert kpis.service_dates(con, SRC) == ["20260922", "20260923"]


def test_otp_overview_shares_add_up(con) -> None:  # type: ignore[no-untyped-def]
    rows = kpis.otp_overview(con, SRC)
    assert {row["grp"] for row in rows} == {"bus", "subway"}
    for row in rows:
        total = row["on_time_share"] + row["early_share"] + row["late_share"]
        assert total == pytest.approx(1.0, abs=1e-3)


def test_least_punctual_routes_are_sorted_and_exclude_thin_hours(con) -> None:  # type: ignore[no-untyped-def]
    rows = kpis.least_punctual_routes(con, SRC, "bus", "20260922", limit=10)
    assert len(rows) == 10
    shares = [row["on_time_share"] for row in rows]
    assert shares == sorted(shares)
    assert all(row["events"] >= kpis.MIN_EVENTS for row in rows)


def test_route_hour_cells_match_the_route_ranking(con) -> None:  # type: ignore[no-untyped-def]
    worst = kpis.least_punctual_routes(con, SRC, "bus", "20260922", limit=1)[0]
    cells = [
        row
        for row in kpis.otp_route_hour(con, SRC, "bus", "20260922")
        if row["route_id"] == worst["route_id"] and row["events"] >= kpis.MIN_EVENTS
    ]
    weighted = sum(row["on_time_share"] * row["events"] for row in cells)
    assert weighted / sum(row["events"] for row in cells) == pytest.approx(
        worst["on_time_share"], abs=1e-4
    )


def test_most_bunched_routes_are_sorted_with_valid_shares(con) -> None:  # type: ignore[no-untyped-def]
    rows = kpis.most_bunched_routes(con, SRC, "bus", "20260922", limit=10)
    shares = [row["bunched_share"] for row in rows]
    assert shares == sorted(shares, reverse=True)
    assert all(0 <= row["bunched_share"] <= 1 for row in rows)
    assert all(row["bunched"] <= row["headways"] for row in rows)


def test_headway_overview_covers_both_modes_and_days(con) -> None:  # type: ignore[no-untyped-def]
    rows = kpis.headway_overview(con, SRC)
    assert {(row["grp"], row["service_date"]) for row in rows} == {
        (grp, day) for grp in ("bus", "subway") for day in ("20260922", "20260923")
    }


def test_feed_score_is_the_share_of_passed_checks(con) -> None:  # type: ignore[no-untyped-def]
    for score in kpis.feed_scores(con, SRC):
        checks = kpis.feed_checks(con, SRC, score["feed"], score["day"])
        assert len(checks) == score["checks"]
        assert sum(check["passed"] for check in checks) == score["passed"]
        assert score["score"] == pytest.approx(100 * score["passed"] / score["checks"], abs=0.05)


def test_delivery_classes_add_up_to_scheduled(con) -> None:  # type: ignore[no-untyped-def]
    for row in kpis.delivery_overview(con, SRC):
        classes = ("delivered", "partial", "missing", "not_run", "unknown")
        assert sum(row[c] for c in classes) == row["scheduled"]


def test_least_delivered_routes_are_sorted(con) -> None:  # type: ignore[no-untyped-def]
    rows = kpis.least_delivered_routes(con, SRC, "bus", "20260922", limit=10)
    shares = [row["not_delivered_share"] for row in rows]
    assert shares == sorted(shares, reverse=True)
    assert all(row["scheduled"] - row["unknown"] >= kpis.MIN_TRIPS for row in rows)


def test_route_scorecards_put_ranked_routes_first_with_valid_intervals(con) -> None:  # type: ignore[no-untyped-def]
    rows = kpis.route_scorecards(con, SRC, "bus")
    ranked = [r for r in rows if r["sufficient"]]
    assert ranked and rows[: len(ranked)] == ranked
    assert [r["rank"] for r in ranked] == sorted(r["rank"] for r in ranked)
    for r in ranked:
        assert r["ci_low"] <= r["on_time_share"] <= r["ci_high"]
        assert r["rank_low"] <= r["rank_high"]


def test_stop_explorer_queries_chain_from_route_to_hours(con) -> None:  # type: ignore[no-untyped-def]
    route = kpis.stop_routes(con, SRC, "subway")[0]
    stops = kpis.route_stops(con, SRC, "subway", route)
    assert stops and all(s["scored_hours"] > 0 for s in stops)
    first = stops[0]
    hours = kpis.stop_hours(con, SRC, "subway", route, first["direction_id"], first["stop_id"])
    assert sum(h["events"] for h in hours) == first["events"]
    for h in hours:
        assert h["ci_low"] <= h["on_time_share"] <= h["ci_high"]
        assert h["sufficient"] == (h["events"] >= 10)


def test_optional_tables_are_detected_per_source() -> None:
    assert SRC.has("route_scorecard")
    assert not SRC.has("no_such_table")


def test_delay_attribution_reconciles_exactly(con) -> None:  # type: ignore[no-untyped-def]
    for row in kpis.delay_overview(con, SRC):
        assert row["attribution_mismatches"] == 0
        assert row["mean_final_delay_s"] == pytest.approx(
            row["mean_inherited_delay_s"] + row["mean_gained_delay_s"], abs=0.11
        )


def test_costly_segments_are_ranked_by_excess(con) -> None:  # type: ignore[no-untyped-def]
    rows = kpis.costly_segments(con, SRC, "bus", 20, limit=10)
    excess = [r["median_excess_s"] for r in rows]
    assert excess == sorted(excess, reverse=True)
    assert all(r["segments"] >= 20 for r in rows)


def test_warning_summary_has_rule_and_baseline_per_outcome(con) -> None:  # type: ignore[no-untyped-def]
    rows = kpis.warning_summary(con, SRC)
    keys = {(r["grp"], r["service_date"], r["outcome"], r["method"]) for r in rows}
    assert len(keys) == len(rows) == 16
    for r in rows:
        assert r["tp"] + r["fn"] == r["positives"]


def test_unknown_source_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRANSITOMETER_APP_SOURCE", "silver")
    with pytest.raises(ValueError, match="golden"):
        kpis.source_from_env()


def test_gold_source_reads_delta_tables_under_the_lakehouse() -> None:
    gold = kpis.Source("gold", "/data/lakehouse")
    assert gold.table("otp_summary") == "delta_scan('/data/lakehouse/gold/otp_summary')"


def test_snapshot_source_reads_parquet_from_its_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRANSITOMETER_APP_SOURCE", "snapshot")
    monkeypatch.delenv("TRANSITOMETER_SNAPSHOT_DIR", raising=False)
    src = kpis.source_from_env()
    assert src == kpis.Source("snapshot", str(kpis.SNAPSHOT_DIR))
    assert src.table("otp_summary").endswith("/showcase/data/otp_summary.parquet'")
