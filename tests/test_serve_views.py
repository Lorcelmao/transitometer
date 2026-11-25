"""The page rules both frontends share, checked on the frozen golden tables."""

from __future__ import annotations

import json
from typing import Any

import pytest

from transitometer.pipeline.service_days import day_base
from transitometer.serve import format as fmt
from transitometer.serve import kpis, views

SRC = kpis.Source("golden", str(kpis.REPO / "golden" / "tables"))
DAYS = ["20260922", "20260923"]
CASES = kpis.REPO / "showcase" / "contract" / "format-cases.json"


@pytest.fixture(scope="module")
def con():  # type: ignore[no-untyped-def]
    connection = kpis.connect(SRC)
    yield connection
    connection.close()


@pytest.mark.parametrize("grp", ["bus", "subway"])
@pytest.mark.parametrize("day", DAYS)
def test_on_time_heatmap_covers_the_ranked_routes_and_flags_thin_cells(con, grp, day) -> None:  # type: ignore[no-untyped-def]
    view = views.on_time(con, SRC, grp, day)
    ranked = [r["route_id"] for r in view["routes"]]
    assert len(ranked) <= views.HEATMAP_ROUTES
    assert {c["route_id"] for c in view["cells"]} == set(ranked)
    assert all(c["scored"] == (c["events"] >= kpis.MIN_EVENTS) for c in view["cells"])
    assert view["ranking"] == view["routes"][: views.RANKED_ROUTES]


def test_headway_classes_and_the_irregular_rest_add_up(con) -> None:  # type: ignore[no-untyped-def]
    for day in DAYS:
        view = views.headways(con, SRC, "bus", day)
        values = {f["key"]: f["value"] for f in view["figures"]}
        total = values["regular"] + values["bunched"] + values["gaps"] + values["irregular"]
        assert total == pytest.approx(1.0)
        assert {c["route_id"] for c in view["cells"]} <= {r["route_id"] for r in view["routes"]}


def test_not_delivered_outcomes_are_missing_and_not_run(con) -> None:  # type: ignore[no-untyped-def]
    view = views.missing_trips(con, SRC, "bus", DAYS[0])
    flagged = {o["key"] for o in view["outcomes"] if o["not_delivered"]}
    assert flagged == {"missing", "not_run"}
    assert [o["order"] for o in view["outcomes"]] == list(range(len(views.OUTCOMES)))
    assert sum(o["trips"] for o in view["outcomes"]) == view["summary"]["scheduled"]
    assert view["caveat"] is None
    assert views.missing_trips(con, SRC, "subway", DAYS[0])["caveat"]["display"].endswith("%")


@pytest.mark.parametrize("grp", ["bus", "subway"])
def test_scorecards_show_the_extremes_of_the_ranking(con, grp) -> None:  # type: ignore[no-untyped-def]
    view = views.route_scorecards(con, SRC, grp)
    ranked = view["ranked"]
    assert all(r["sufficient"] for r in ranked) and not any(
        r["sufficient"] for r in view["unranked"]
    )
    least, most = view["least"], view["most"]
    assert {r["route_id"] for r in least} == {r["route_id"] for r in ranked[-views.SHOWN_ROUTES :]}
    assert {r["route_id"] for r in most} == {r["route_id"] for r in ranked[: views.SHOWN_ROUTES]}
    assert [r["on_time_share"] for r in least] == sorted(r["on_time_share"] for r in least)
    assert [r["on_time_share"] for r in most] == sorted(
        (r["on_time_share"] for r in most), reverse=True
    )


def test_a_stop_reads_the_same_alone_and_within_its_route(con) -> None:  # type: ignore[no-untyped-def]
    route = views.stop_routes(con, SRC, "bus")[0]
    stops = views.route_stop_details(con, SRC, "bus", route)
    assert stops
    for stop in stops[:5]:
        alone = views.stop_detail(con, SRC, "bus", route, stop["direction_id"], stop["stop_id"])
        assert stop["hours"] == alone["hours"] and stop["figures"] == alone["figures"]
        values = {f["key"]: f["value"] for f in stop["figures"]}
        assert values["arrivals"] == sum(h["events"] for h in stop["hours"])
        assert values["scored_hours"] == sum(h["sufficient"] for h in stop["hours"])


@pytest.mark.parametrize("grp", ["bus", "subway"])
def test_early_warning_verdicts_apply_the_declared_rule(con, grp) -> None:  # type: ignore[no-untyped-def]
    rows = [r for r in kpis.warning_summary(con, SRC) if r["grp"] == grp]
    for verdict in views.early_warning(con, SRC, grp)["verdicts"]:
        held = {
            r["method"]: r
            for r in rows
            if r["service_date"] == views.HELD_OUT_DAY and r["outcome"] == verdict["outcome"]
        }
        rule, base = held["rule"], held["baseline"]
        expected = rule["f1"] > base["f1"] and rule["precision"] >= views.MIN_PRECISION
        assert verdict["passed"] is expected
        assert verdict["verdict"] == ("passed" if expected else "did not pass")


@pytest.mark.parametrize("grp", ["bus", "subway"])
def test_the_dispatcher_list_adds_up_to_the_rules_own_counts(con, grp) -> None:  # type: ignore[no-untyped-def]
    day = views.HELD_OUT_DAY
    summary = {
        r["outcome"]: r
        for r in kpis.warning_summary(con, SRC)
        if r["grp"] == grp and r["service_date"] == day and r["method"] == "rule"
    }
    every_route = kpis.warning_routes(con, SRC, grp, day, min_decisions=0)
    hours = kpis.warning_hours(con, SRC, grp, day, day_base(day))
    for rows in (every_route, hours):
        for outcome in ("late", "bunched"):
            warned = sum(int(r[f"warned_{outcome}"]) for r in rows)
            hits = sum(int(r[f"{outcome}_hits"]) for r in rows)
            assert warned == summary[outcome]["tp"] + summary[outcome]["fp"]
            assert hits == summary[outcome]["tp"]
        assert sum(int(r["decisions"]) for r in rows) == summary["late"]["decisions"]

    listed = views.early_warning(con, SRC, grp)["dispatcher"]
    assert listed["day"] == day
    routes = listed["routes"]
    assert 0 < len(routes) <= views.RANKED_ROUTES
    assert all(r["decisions"] >= views.WARNING_MIN_DECISIONS for r in routes)
    assert [r["warnings"] for r in routes] == sorted((r["warnings"] for r in routes), reverse=True)
    examples = listed["examples"]
    assert len({(e["kind"], e["route_id"]) for e in examples}) == len(examples)  # one per route
    for e in examples:
        assert e["late"] is (e["kind"] == "warning came true")


def test_feed_health_names_exactly_the_failed_checks(con) -> None:  # type: ignore[no-untyped-def]
    for day in views.feed_days(con, SRC):
        for feed in views.feed_health(con, SRC, day)["feeds"]:
            failed = [c["check"] for c in feed["checks"] if not c["passed"]]
            assert sorted(feed["failed"]) == sorted(failed)


def _case_output(case: dict[str, Any]) -> str:
    result: str = getattr(fmt, case["fn"])(*case["args"])
    return result


def test_formatters_match_the_shared_cases() -> None:
    """The same vectors drive the Next.js formatter tests (showcase/contract/format-cases.json)."""
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    assert len(cases) >= 20
    for case in cases:
        assert _case_output(case) == case["expected"], case


SNAPSHOT_SRC = kpis.Source("snapshot", str(kpis.SNAPSHOT_DIR))
# The bounding box the feed-quality checks use for "fixes outside NYC" (with a margin for stops).
NYC = {"lat": (40.40, 41.10), "lon": (-74.40, -73.60)}


@pytest.mark.skipif(
    not SNAPSHOT_SRC.has("stop_locations"), reason="snapshot without stop locations yet"
)
@pytest.mark.parametrize("grp", ["bus", "subway"])
def test_the_stop_map_pools_each_stop_and_puts_the_least_reliable_first(grp: str) -> None:
    with kpis.connect(SNAPSHOT_SRC) as con:
        view = views.stop_map(con, SNAPSHOT_SRC, grp)
        totals = con.execute(
            f"SELECT stop_id, sum(events), sum(on_time) FROM "
            f"{SNAPSHOT_SRC.table('stop_hour_reliability')} WHERE grp = ? GROUP BY stop_id",
            [grp],
        ).fetchall()
    pooled = {stop: (events, on_time) for stop, events, on_time in totals}
    assert view["stops"]
    for stop in view["stops"]:
        assert (stop["events"], stop["on_time"]) == pooled[stop["stop_id"]]
        assert stop["sufficient"] == (stop["events"] >= views.MIN_CELL_EVENTS)
        assert NYC["lat"][0] < stop["lat"] < NYC["lat"][1]
        assert NYC["lon"][0] < stop["lon"] < NYC["lon"][1]
    shares = [s["on_time_share"] for s in view["stops"] if s["sufficient"]]
    assert shares == sorted(shares)
    assert [s["stop_id"] for s in view["worst"]] == [
        s["stop_id"] for s in view["stops"][: len(view["worst"])]
    ]


def _all_stops(con, grp: str, day: str) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    return next(
        r
        for r in kpis.otp_overview(con, SRC)
        if r["grp"] == grp and r["service_date"] == day and r["scope"] == "all_stops"
    )


@pytest.mark.parametrize("grp", ["bus", "subway"])
@pytest.mark.parametrize("day", DAYS)
def test_the_hourly_profile_adds_up_to_the_day(con, grp, day) -> None:  # type: ignore[no-untyped-def]
    """Arrivals-weighted hours reproduce the all-stops figure the overview headline shows."""
    view = views.overview(con, SRC, grp, day)
    hours = view["hours"]
    total = _all_stops(con, grp, day)
    assert sum(h["events"] for h in hours) == total["events"]
    weighted = sum(h["on_time_share"] * h["events"] for h in hours) / total["events"]
    assert weighted == pytest.approx(total["on_time_share"], abs=5e-5)
    assert all(h["sufficient"] == (h["events"] >= views.HOURLY_MIN_EVENTS) for h in hours)
    assert all(f["basis"] for f in view["figures"])


def test_delivery_labels_say_what_the_feed_showed() -> None:
    labels = dict(views.OUTCOMES)
    assert labels["missing"] == "Never reported"
    assert labels["not_run"] == "Announced, never moved"
    assert "not proof" in views.MISSING_DEFINITIONS


@pytest.mark.skipif(
    not SNAPSHOT_SRC.has("stop_locations"), reason="snapshot without stop locations yet"
)
def test_hero_cells_keep_every_stop_and_arrival() -> None:
    with kpis.connect(SNAPSHOT_SRC) as con:
        hero = views.hero_map(con, SNAPSHOT_SRC)
        stops = [s for grp in views.GROUPS for s in kpis.stop_map(con, SNAPSHOT_SRC, grp)]
    assert hero["stops"] == len(stops)
    assert sum(c["events"] for c in hero["cells"]) == sum(s["events"] for s in stops)
    assert all(c["sufficient"] == (c["events"] >= views.MIN_CELL_EVENTS) for c in hero["cells"])


@pytest.mark.skipif(
    not SNAPSHOT_SRC.has("stop_locations"), reason="snapshot without stop locations yet"
)
def test_findings_are_backed_by_the_tables() -> None:
    with kpis.connect(SNAPSHOT_SRC) as con:
        found = {f["key"]: f for f in views.findings(con, SNAPSHOT_SRC)}
        ranked = views.route_scorecards(con, SNAPSHOT_SRC, "bus")["ranked"]
        hours = [
            h
            for h in kpis.hourly_on_time(con, SNAPSHOT_SRC, "bus")
            if h["events"] >= views.HOURLY_MIN_EVENTS
        ]
    assert set(found) == {"modes", "hours", "route", "warning"}
    assert ranked[-1]["route_id"] in found["route"]["headline"]
    worst = min(hours, key=lambda h: (h["on_time_share"], h["service_hour"]))
    assert found["hours"]["value"] == fmt.pct(worst["on_time_share"])


def test_pipeline_facts_come_from_the_evidence_files() -> None:
    folder = kpis.SNAPSHOT_DIR / "evidence"
    if not (folder / "replay-report.json").exists():
        pytest.skip("no snapshot evidence yet")
    facts = views.pipeline(folder)
    replay = json.loads((folder / "replay-report.json").read_text(encoding="utf-8"))
    assert facts["messages"] == fmt.count(sum(f["messages"] for f in replay["feeds"]))
    gold = json.loads((folder / "validation-gold.json").read_text(encoding="utf-8"))
    passed = sum(t["ok"] for t in gold["tables"].values())
    assert facts["gold"] == f"{passed} / {len(gold['tables'])}"


def test_shared_badge_rules_apply_the_named_thresholds() -> None:
    assert views.on_time_badge(0.499) == {"label": "Below 50 %", "tone": "attention"}
    assert views.on_time_badge(0.500) == {"label": "Higher on-time", "tone": "pass"}
    assert views.bunching_badge(0.049) == {"label": "Low", "tone": "pass"}
    assert views.bunching_badge(0.050) == {"label": "Watch", "tone": "attention"}
    assert views.gapping_badge(0.049) == {"label": "Low", "tone": "pass"}
    assert views.gapping_badge(0.050) == {"label": "Watch", "tone": "fail"}
    assert views.not_delivered_badge(0.099) == {"label": "Check feed", "tone": "attention"}
    assert views.not_delivered_badge(0.100) == {"label": "Elevated", "tone": "fail"}
    assert views.feed_score_badge(0) == {"label": "All passed", "tone": "pass"}
    assert views.feed_score_badge(1) == {"label": "1 failed", "tone": "fail"}
    assert views.feed_health_card_badge(0, 10) == {"label": "All 10 passed", "tone": "pass"}
    assert views.feed_health_card_badge(1, 10) == {"label": "1 failed", "tone": "fail"}
    assert views.feed_health_card_badge(3, 10) == {"label": "3 failed", "tone": "fail"}
    assert views.feed_health_status_badge(0) == {"label": "All checks passed", "tone": "pass"}
    assert views.feed_health_status_badge(1) == {"label": "1 check exceeded limit", "tone": "fail"}
    assert views.feed_health_status_badge(3) == {"label": "3 checks exceeded limit", "tone": "fail"}


def test_stop_map_bands_and_delta_pts_share_one_rule() -> None:
    assert views.stop_map_band_index(0.50, False) == -1
    assert views.stop_map_band_index(0.299, True) == 0
    assert views.stop_map_band_index(0.30, True) == 1
    assert views.stop_map_band_index(0.40, True) == 2
    assert views.stop_map_band_index(0.50, True) == 3
    assert views.stop_map_band_index(0.65, True) == 4
    assert views.stop_map_delta_pts(0.555, 0.455, True) == "+10.0"
    assert views.stop_map_delta_pts(0.355, 0.455, True) == "-10.0"
    assert views.stop_map_delta_pts(0.555, 0.455, False) is None
    assert fmt.pts_delta(0.0) == "+0.0"


@pytest.mark.parametrize("grp", ["bus", "subway"])
@pytest.mark.parametrize("day", DAYS)
def test_views_share_badges_takeaways_and_hour_labels(con, grp, day) -> None:  # type: ignore[no-untyped-def]
    ov = views.overview(con, SRC, grp, day)
    hw = views.headways(con, SRC, grp, day)
    mt = views.missing_trips(con, SRC, grp, day)
    dl = views.delay(con, SRC, grp, day)
    otp = views.on_time(con, SRC, grp, day)

    # Overview and sub-pages agree on the exact same badge for shared metrics.
    ov_by_key = {f["key"]: f for f in ov["figures"]}
    hw_by_key = {f["key"]: f for f in hw["figures"]}
    mt_by_key = {f["key"]: f for f in mt["figures"]}
    assert ov_by_key["bunched"]["badge"] == hw_by_key["bunched"]["badge"]
    assert ov_by_key["not_delivered"]["badge"] == mt_by_key["not_delivered"]["badge"]

    for view in (ov, hw, mt, dl, otp):
        assert view["takeaway"]

    # Hourly rows stay ordered chronologically and tag hours >= 24 with (+1).
    for rows in (ov["hours"], otp["cells"]):
        for row in rows:
            hr = int(row["service_hour"])
            assert row["hour_label"] == fmt.service_hour(hr)
            if hr >= 24:
                assert row["hour_label"].endswith("(+1)")
    ov_hours = [int(h["service_hour"]) for h in ov["hours"]]
    assert ov_hours == sorted(ov_hours)
    if any(hr >= 24 for hr in ov_hours):
        idx_23 = ov_hours.index(23)
        idx_24 = next(i for i, hr in enumerate(ov_hours) if hr >= 24)
        assert idx_24 > idx_23


def test_post_midnight_hours_on_snapshot_keep_order_and_suffix() -> None:
    if not (kpis.SNAPSHOT_DIR / "manifest.json").exists():
        pytest.skip("no snapshot in showcase/data yet")
    with kpis.connect(SNAPSHOT_SRC) as con:
        ov = views.overview(con, SNAPSHOT_SRC, "bus", DAYS[0])
        ew = views.early_warning(con, SNAPSHOT_SRC, "bus")["dispatcher"]
    ov_hours = [int(h["service_hour"]) for h in ov["hours"]]
    assert max(ov_hours) >= 24
    assert ov_hours == sorted(ov_hours)
    assert ov["hours"][ov_hours.index(24)]["hour_label"] == "00:00 (+1)"
    ew_hours = [int(h["service_hour"]) for h in ew["hours"]]
    assert ew_hours == sorted(ew_hours)
    for row in ew["hours"]:
        assert row["hour_label"] == fmt.service_hour(int(row["service_hour"]))
