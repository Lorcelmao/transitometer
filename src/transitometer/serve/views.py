"""Page views shared by both frontends: the data, rules, labels and display strings of each page.

A view is a pure function of a connection, a source and the page's filters. It returns plain,
JSON-serialisable data: raw rows for charts and tables, display strings (serve/format.py) for every
headline figure, and the page's metric definitions. The Streamlit app renders views directly;
`python tasks.py web-data` writes them as JSON for the Next.js site. Neither frontend defines a
threshold, ranking size, pass rule, label or definition of its own, so both show the same numbers.
"""

from __future__ import annotations

import statistics
from pathlib import Path
from typing import Any

import duckdb

from transitometer.pipeline.service_days import day_base
from transitometer.serve import evidence, kpis
from transitometer.serve.format import (
    check_threshold,
    check_value,
    count,
    day_label,
    decimal,
    minutes,
    pct,
    pts_delta,
    score,
    service_hour,
    service_hour_short,
)
from transitometer.serve.kpis import MIN_EVENTS, MIN_TRIPS, Source

Con = duckdb.DuckDBPyConnection
Row = dict[str, Any]

HEATMAP_ROUTES = 25  # on-time heatmap: the least punctual routes, hour by hour
HOURLY_MIN_EVENTS = 1000  # hourly profile: hours with fewer arrivals are shown, not compared
HERO_CELL = (0.006, 0.008)  # hero map grid in degrees (latitude, longitude): about 670 m square
RANKED_ROUTES = 15  # ranking charts
SHOWN_ROUTES = 20  # scorecard chart: least or most punctual ranked routes
MIN_CELL_EVENTS = 10  # golden min_events: stop-hours with fewer arrivals are not scored
MIN_ROUTE_TRIPS = 5  # golden min_trips: routes with fewer trips are not ranked
MIN_SEGMENTS = 20  # segment-hours with fewer observations are not ranked
DEVELOPMENT_DAY, HELD_OUT_DAY = "20260922", "20260923"  # rules were tuned on the first day only
MIN_PRECISION = 0.6  # early-warning acceptance, declared before the held-out day was computed

# --- shared display thresholds, status badges and diverging map bands -------------------------
# Every status threshold, badge label/tone, colour-scale boundary and day-level takeaway lives
# here once so Streamlit and the Next.js site cannot diverge (report section 5.3).

ON_TIME_BELOW_HALF_THRESHOLD = 0.50
"""Overview punctuality threshold: shares below 50 % receive 'Below 50 %' (attention);
shares at or above 50 % receive 'Higher on-time' (pass)."""

ON_TIME_TWO_THIRDS_LOW = 0.60
ON_TIME_TWO_THIRDS_HIGH = 0.75
"""Plain-English Overview takeaway band: shares in [60 %, 75 %) read 'Roughly two-thirds'."""

HEADWAY_WATCH_THRESHOLD = 0.05
"""Headways and Overview bunching/gapping threshold: shares at or above 5 % receive 'Watch'
(attention for bunching, fail for long gaps); lower shares receive 'Low' (pass)."""

BUNCHING_PEER_RATIO_HIGH = 10.0
"""Overview takeaway ratio threshold: when a mode's bunching share is at least 10x its peer
mode on the same service day, the takeaway highlights the tenfold gap."""

NOT_DELIVERED_ELEVATED_THRESHOLD = 0.10
"""Trip-delivery threshold shared by Overview and Trip delivery: observable scheduled trips not
seen running at or above 10 % receive 'Elevated' (fail); lower shares receive 'Check feed'
(attention) because absence from a real-time feed is evidence, not proof."""

HEADWAY_REGULAR_BADGE: Row = {"label": "On rhythm", "tone": "pass"}
"""Static badge for regular headways (within 20 % of the scheduled interval)."""

HEADWAY_IRREGULAR_BADGE: Row = {"label": "Off rhythm", "tone": "neutral"}
"""Static badge for irregular headways (outside regular band, not bunched or a gap)."""

UNKNOWN_TRIPS_BADGE: Row = {"label": "Excluded", "tone": "neutral"}
"""Static badge for scheduled trips that could not be judged and are excluded from the rate."""

FINDING_ROUTE_BADGE: Row = {"label": "Below route median", "tone": "fail"}
"""Badge on the Overview key-finding card for the least punctual ranked bus route."""

STOP_MAP_BANDS: tuple[Row, ...] = (
    {"id": 0, "label": "Critical", "range": "under 30 %", "color": "#b3261e", "max": 0.30},
    {"id": 1, "label": "Poor", "range": "30 to 40 %", "color": "#c2570a", "max": 0.40},
    {"id": 2, "label": "Typical", "range": "40 to 50 %", "color": "#64748b", "max": 0.50},
    {"id": 3, "label": "Above typical", "range": "50 to 65 %", "color": "#2b6cb0", "max": 0.65},
    {"id": 4, "label": "Reliable", "range": "65 % or more", "color": "#0b3b75", "max": None},
)
"""Unified 5-class WCAG AA diverging on-time scale for /diagnostics/map/, anchored near the
equal-weighted bus stop median (45.5 %) and shared identically across bus and subway."""

STOP_MAP_THIN_BAND: Row = {
    "id": "thin",
    "label": f"Under {MIN_CELL_EVENTS} arrivals",
    "color": "#475569",
}
"""Hollow-outline map category for stops with fewer than MIN_CELL_EVENTS arrivals."""

GROUPS = {"bus": "MTA Bus", "subway": "NYC Subway (lines 1 to 7, S)"}
SHORT_GROUPS = {"bus": "Bus", "subway": "Subway"}
FEEDS = {
    "bus_tu": "Bus trip updates",
    "subway_tu": "Subway trip updates",
    "bus_vp": "Bus vehicle positions",
}
EVIDENCE_FEEDS = {
    "trip_updates.bus": "Bus trip updates",
    "trip_updates.subway": "Subway trip updates",
    "vehicle_positions.bus": "Bus vehicle positions",
}
# Delivery outcomes in display order; NOT_DELIVERED lists those counted as "not seen running".
# Labels say what the feed showed, not more: absence from a feed is evidence, not proof.
OUTCOMES = [
    ("delivered", "Delivered (most stops seen)"),
    ("partial", "Partly observed"),
    ("not_run", "Announced, never moved"),
    ("missing", "Never reported"),
    ("unknown", "Could not be judged"),
]
NOT_DELIVERED = {"missing", "not_run"}
# Feed-health checks: plain name, what it measures, and its unit.
FEED_CHECKS: dict[str, tuple[str, str, str]] = {
    "max_gap_s": (
        "Longest snapshot gap",
        "Longest time between two consecutive feed snapshots",
        "s",
    ),
    "missed_poll_share": (
        "Missed polls",
        "Polls that returned no new snapshot (fetch gap > 1.5× the usual interval)",
        "%",
    ),
    "header_lag_p99_s": ("Publish delay (p99)", "Time from the feed's timestamp to our fetch", "s"),
    "unknown_stop_share": ("Unknown stop IDs", "Listed stops that are not in the timetable", "%"),
    "unknown_trip_share": (
        "Unmatched trips",
        "Real-time trips that match no scheduled trip (added service or unresolvable IDs)",
        "%",
    ),
    "stuck_share": (
        "Stuck predictions",
        "Stops still listed with a prediction already > 90 s in the past (timetable echo)",
        "%",
    ),
    "not_run_share": (
        "Announced but not run",
        "Scheduled trips announced but never seen moving",
        "%",
    ),
    "ambiguous_share": ("Ambiguous stops", "Trip-stops reported by more than one vehicle", "%"),
    "fix_age_p99_s": (
        "GPS fix age (p99)",
        "Age of a vehicle's GPS fix when the feed published it",
        "s",
    ),
    "stale_fix_share": ("Stale GPS fixes", "GPS fixes older than 2 minutes when published", "%"),
    "jump_share": ("GPS jumps", "Consecutive fixes > 200 m apart at > 108 km/h implied speed", "%"),
    "out_of_bbox_share": ("Fixes outside NYC", "GPS fixes outside the New York service area", "%"),
}
DATASETS = [
    ("MTA Bus trip updates", "Predicted stop times per trip", "gtfsrt.io archive (MTA feed)"),
    ("MTA Bus vehicle positions", "GPS position of every bus", "gtfsrt.io archive (MTA feed)"),
    ("NYC Subway trip updates", "Lines 1 to 7 and S", "gtfsrt.io archive (MTA feed)"),
    ("MTA static timetables (GTFS)", "Scheduled trips and stop times", "MTA"),
]


def _badge(label: str, tone: str) -> Row:
    """A status badge shared by both frontends: label text and semantic tone."""
    return {"label": label, "tone": tone}


def on_time_badge(share: float | None) -> Row | None:
    """Overview punctuality badge based on ON_TIME_BELOW_HALF_THRESHOLD."""
    if share is None:
        return None
    if share < ON_TIME_BELOW_HALF_THRESHOLD:
        return _badge("Below 50 %", "attention")
    return _badge("Higher on-time", "pass")


def bunching_badge(share: float | None) -> Row | None:
    """Bunching badge shared by Overview and Headways (HEADWAY_WATCH_THRESHOLD)."""
    if share is None:
        return None
    if share >= HEADWAY_WATCH_THRESHOLD:
        return _badge("Watch", "attention")
    return _badge("Low", "pass")


def gapping_badge(share: float | None) -> Row | None:
    """Long-gap headway badge (HEADWAY_WATCH_THRESHOLD)."""
    if share is None:
        return None
    if share >= HEADWAY_WATCH_THRESHOLD:
        return _badge("Watch", "fail")
    return _badge("Low", "pass")


def not_delivered_badge(share: float | None) -> Row | None:
    """Trip-delivery badge shared by Overview and Trip delivery."""
    if share is None:
        return None
    if share >= NOT_DELIVERED_ELEVATED_THRESHOLD:
        return _badge("Elevated", "fail")
    return _badge("Check feed", "attention")


def feed_score_badge(failed_count: int) -> Row:
    """Overview feed-quality KPI badge from the number of failed checks."""
    if failed_count > 0:
        return _badge(f"{failed_count} failed", "fail")
    return _badge("All passed", "pass")


def feed_health_card_badge(failed_count: int, total: int) -> Row:
    """Feed-health summary card badge from failed and total check counts."""
    if failed_count > 0:
        return _badge(f"{failed_count} failed", "fail")
    return _badge(f"All {total} passed", "pass")


def feed_health_status_badge(failed_count: int) -> Row:
    """Feed-health check table status badge."""
    if failed_count > 0:
        noun = "check" if failed_count == 1 else "checks"
        return _badge(f"{failed_count} {noun} exceeded limit", "fail")
    return _badge("All checks passed", "pass")


def stop_map_band_index(share: float | None, sufficient: bool = True) -> int:
    """Map an on-time share onto STOP_MAP_BANDS (0..4), or -1 for thinly observed stops."""
    if not sufficient or share is None:
        return -1
    for band in STOP_MAP_BANDS:
        limit = band["max"]
        if limit is None or share < limit:
            return int(band["id"])
    return len(STOP_MAP_BANDS) - 1


def stop_map_delta_pts(
    share: float | None, median_share: float | None, sufficient: bool = True
) -> str | None:
    """Signed percentage-point difference against the mode's stop median, or None if unscored."""
    if not sufficient or share is None or median_share is None:
        return None
    return pts_delta(share - median_share)


def _linear_quantile(sorted_values: list[float], p: float) -> float:
    """Linear-interpolated quantile over a sorted non-empty list of floats."""
    if not sorted_values:
        return 0.0
    idx = (len(sorted_values) - 1) * p
    lo = int(idx)
    hi = min(len(sorted_values) - 1, lo + 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (idx - lo)


def _overview_takeaway(
    grp: str,
    otp: Row | None,
    heads: Row | None,
    peer_heads: Row | None,
    fail_count: int,
    has_caveat: bool,
) -> str:
    """Plain-English day takeaway computed from the day's metrics and shared thresholds."""
    mode_word = "bus" if grp == "bus" else "subway"
    peer_word = "subway" if grp == "bus" else "bus"

    on_time_val = otp["on_time_share"] if otp else None
    if on_time_val is None:
        punctuality = f"No {mode_word} arrivals were recorded"
    elif on_time_val < ON_TIME_BELOW_HALF_THRESHOLD:
        punctuality = f"Fewer than half of {mode_word} arrivals kept to schedule"
    elif ON_TIME_TWO_THIRDS_LOW <= on_time_val < ON_TIME_TWO_THIRDS_HIGH:
        punctuality = f"Roughly two-thirds of {mode_word} arrivals kept to schedule"
    elif on_time_val >= ON_TIME_TWO_THIRDS_HIGH:
        punctuality = f"More than three-quarters of {mode_word} arrivals kept to schedule"
    else:
        punctuality = f"More than half of {mode_word} arrivals kept to schedule"

    bunched_val = heads["bunched_share"] if heads else None
    peer_bunched = peer_heads["bunched_share"] if peer_heads else None
    if (
        bunched_val is not None
        and peer_bunched is not None
        and peer_bunched > 0
        and (bunched_val / peer_bunched) >= BUNCHING_PEER_RATIO_HIGH
    ):
        bunching_clause = f", bunching ran more than ten times higher than {peer_word}"
    elif bunched_val is not None and bunched_val < HEADWAY_WATCH_THRESHOLD:
        bunching_clause = " with low bunching"
    elif bunched_val is not None:
        bunching_clause = f", with {pct(bunched_val)} of headways bunched"
    else:
        bunching_clause = ""

    if fail_count == 0:
        feed_clause = ", and all feed quality checks passed."
    elif fail_count == 1:
        feed_clause = ", and 1 feed quality check exceeded its limit."
    elif has_caveat:
        feed_clause = (
            f", but {fail_count} feed quality checks failed and warrant caution when reading "
            "missing trips."
        )
    else:
        feed_clause = f", and {fail_count} feed quality checks exceeded their limits."
    return f"{punctuality}{bunching_clause}{feed_clause}"


def _figure(
    key: str,
    label: str,
    value: Any,
    display: str,
    help: str | None = None,
    basis: str | None = None,
    badge: Row | None = None,
) -> Row:
    """A headline number: raw value for charts and tests, display string for both frontends,
    sample size (`basis`), and optional shared status badge (`label` + `tone`)."""
    return {
        "key": key,
        "label": label,
        "value": value,
        "display": display,
        "help": help,
        "basis": basis,
        "badge": badge,
    }


def _pick(rows: list[Row], **match: Any) -> Row | None:
    return next((r for r in rows if all(r.get(k) == v for k, v in match.items())), None)


# --- overview --------------------------------------------------------------------------------


def overview(con: Con, src: Source, grp: str, day: str) -> Row:
    """The day at a glance: punctuality, bunching, delivery and feed quality of one mode."""
    otp = _pick(kpis.otp_overview(con, src), grp=grp, service_date=day, scope="all_stops")
    headway_rows = kpis.headway_overview(con, src)
    heads = _pick(headway_rows, grp=grp, service_date=day)
    peer_grp = "subway" if grp == "bus" else "bus"
    peer_heads = _pick(headway_rows, grp=peer_grp, service_date=day)
    trips = _pick(kpis.delivery_overview(con, src), grp=grp, service_date=day)
    feed = _pick(kpis.feed_scores(con, src), feed=f"{grp}_tu", day=day)
    observable = trips["scheduled"] - trips["unknown"] if trips else None
    fail_count = int(feed["checks"] - feed["passed"]) if feed else 0
    failed_raw = feed["failed_checks"] if feed else ""
    failed_names = [_check_name(m) for m in failed_raw.split(", ")] if failed_raw else []
    feed_checks = (
        {"passed": int(feed["passed"]), "total": int(feed["checks"]), "failed": failed_names}
        if feed
        else None
    )
    caveat = _subway_caveat(con, src, day) if grp == "subway" else None
    figures = [
        _figure(
            "on_time",
            "Inferred arrivals on time",
            otp and otp["on_time_share"],
            pct(otp["on_time_share"]) if otp else "—",
            "Share of inferred arrivals at intermediate scheduled stops that were at most 1 min "
            "early and at most 5 min late (the MTA's on-time band).",
            f"of {count(otp['events'])} inferred arrivals" if otp else None,
            badge=on_time_badge(otp["on_time_share"] if otp else None),
        ),
        _figure(
            "bunched",
            "Headways bunched",
            heads and heads["bunched_share"],
            pct(heads["bunched_share"]) if heads else "—",
            "Share of observed gaps between consecutive vehicles that were at most a quarter of "
            "the scheduled gap: vehicles arriving in clumps.",
            f"of {count(heads['headways'])} observed headways" if heads else None,
            badge=bunching_badge(heads["bunched_share"] if heads else None),
        ),
        _figure(
            "not_delivered",
            "Scheduled trips not seen running",
            trips and trips["not_delivered_share"],
            pct(trips["not_delivered_share"]) if trips else "—",
            "Trips never reported in the feed, or announced but never seen moving, as a share of "
            "the scheduled trips the feed could observe. Absence from the feed is evidence, not "
            "proof, that a trip did not run.",
            f"of {count(observable)} observable scheduled trips" if trips else None,
            badge=not_delivered_badge(trips["not_delivered_share"] if trips else None),
        ),
        _figure(
            "feed_score",
            "Feed quality score",
            feed and feed["score"],
            score(feed["score"]) if feed else "—",
            "Share of the feed's data-quality checks that passed (trip-update feed of this "
            "mode, this day).",
            f"{feed['passed']} of {feed['checks']} checks passed" if feed else None,
            badge=feed_score_badge(fail_count) if feed else None,
        ),
    ]
    hours = [
        {
            **h,
            "hour_label": service_hour(int(h["service_hour"])),
            "display": pct(h["on_time_share"]),
            "sufficient": h["events"] >= HOURLY_MIN_EVENTS,
        }
        for h in kpis.hourly_on_time(con, src, grp, day)
    ]
    return {
        "grp": grp,
        "group_label": GROUPS[grp],
        "day": day,
        "day_label": day_label(day),
        "takeaway": _overview_takeaway(grp, otp, heads, peer_heads, fail_count, caveat is not None),
        "feed_checks": feed_checks,
        "figures": figures,
        "hours": hours,
        "hourly_min_events": HOURLY_MIN_EVENTS,
        "caveat": caveat,
    }


def _subway_caveat(con: Con, src: Source, day: str) -> Row:
    """Subway trips whose IDs match no timetable trip: some 'never reported' trips ran as these."""
    unmatched = kpis.feed_metric(con, src, "subway_tu", day, "unknown_trip_share")
    return {
        "value": unmatched,
        "display": pct(unmatched),
        "text": (
            f"**Read the subway's trip figures with care.** {pct(unmatched)} of the subway's "
            "real-time trips on this day could not be matched to a scheduled trip (their IDs "
            "differ from the timetable). Some scheduled trips counted as never reported probably "
            "ran under such an ID."
        ),
    }


def trust(folder: Path) -> Row:
    """Headline of the validation evidence: source integrity and golden parity."""
    integrity, parity = evidence.source_integrity(folder), evidence.golden_parity(folder)
    rows = sum(f["archive_rows"] for f in integrity["feeds"]) if integrity["available"] else None
    passed = sum(layer["passed"] for layer in parity["layers"])
    total = sum(layer["total"] for layer in parity["layers"])
    all_ok = bool(integrity.get("ok") and parity["ok"])
    return {
        "integrity": {
            "available": integrity["available"],
            "ok": integrity.get("ok", False),
            "archive_rows": rows,
            "archive_rows_display": count(rows),
            "status": "checks passed" if integrity.get("ok") else "a check failed",
        },
        "parity": {
            "available": parity["available"],
            "ok": parity["ok"],
            "passed": passed,
            "total": total,
            # Per layer, so a reader sees what was compared (not one ambiguous total).
            "display": ", ".join(
                f"{layer['layer'].title()} {layer['passed']} / {layer['total']}"
                for layer in parity["layers"]
            ),
        },
        "badge": (
            _badge("Parity and integrity checks passed", "pass")
            if all_ok
            else _badge("Check validation report", "fail")
        ),
    }


# --- reliability: on-time (BR1), headways (BR2), missing trips (BR3) ---------------------------

OTP_DEFINITIONS = (
    "- **Arrival:** inferred from the trip-update feed. A feed lists the stops a vehicle has "
    "not served yet; when a stop drops off the list while the trip is still reported, the "
    "prediction in the last snapshot that listed it is taken as the arrival time.\n"
    "- **Counted stops:** intermediate stops of trips matched to the timetable. First stops "
    "(the feed echoes the timetable there) and last stops (the trip simply leaves the feed) "
    "are excluded; stops reported by several vehicles at once are excluded as ambiguous.\n"
    "- **On time:** delay between −60 s and +300 s; delay = inferred arrival − scheduled "
    "arrival.\n"
    "- **Late:** more than 5 min late. **Early:** more than 1 min early. On time, late and "
    "early add up to 100 % of the counted arrivals (up to rounding).\n"
    "- **Median delay:** the middle delay of the arrivals counted (negative = early).\n"
    f"- **Route ranking:** route-hours with at least {MIN_EVENTS} arrivals, weighted by "
    "arrivals.\n"
    "- **Bus last stops** are measured separately from GPS positions and are not part of "
    "these numbers."
)


def on_time(con: Con, src: Source, grp: str, day: str) -> Row:
    """BR1: the least punctual routes, hour by hour (thin cells flagged), and their ranking."""
    routes = kpis.least_punctual_routes(con, src, grp, day, limit=HEATMAP_ROUTES)
    ranked = {r["route_id"] for r in routes}
    cells = [
        {
            **cell,
            "hour_label": service_hour(int(cell["service_hour"])),
            "hour_short": service_hour_short(int(cell["service_hour"])),
            "scored": cell["events"] >= MIN_EVENTS,
        }
        for cell in kpis.otp_route_hour(con, src, grp, day)
        if cell["route_id"] in ranked
    ]
    ranking = routes[:RANKED_ROUTES]
    day_text = day_label(day)
    worst = ranking[0] if ranking else None
    takeaway = (
        f"On {day_text}, route {worst['route_id']} was the least punctual of the {GROUPS[grp]} "
        f"routes: {pct(worst['on_time_share'])} of its {count(worst['events'])} observed arrivals "
        "were on time."
        if worst is not None
        else None
    )
    return {
        "day": day,
        "day_label": day_text,
        "takeaway": takeaway,
        "routes": routes,
        "cells": cells,
        "ranking": ranking,
        "min_events": MIN_EVENTS,
        "definitions": OTP_DEFINITIONS,
    }


HEADWAY_DEFINITIONS = (
    "- **Observed headway:** time between consecutive passages of two *different* vehicles "
    "of the same route at the same stop (stop IDs are directional).\n"
    "- **Reference:** the median scheduled headway at that stop in the same hour.\n"
    "- **Classes:** bunched ≤ 0.25 × reference; gap ≥ 2 × reference; regular within ±20 % "
    "of the reference; irregular otherwise. The four shares add up to 100 % (up to "
    "rounding).\n"
    "- Passages include added (unscheduled) service and stops passed by several vehicles, "
    "because a waiting rider sees those vehicles too.\n"
    f"- **Route ranking:** routes with at least {MIN_EVENTS} observed headways."
)


def headways(con: Con, src: Source, grp: str, day: str) -> Row:
    """BR2: headway classes of the day, the most bunched routes and their hours."""
    row = _pick(kpis.headway_overview(con, src), grp=grp, service_date=day)
    routes = kpis.most_bunched_routes(con, src, grp, day, limit=RANKED_ROUTES)
    shown = {r["route_id"] for r in routes}
    cells = [
        {**c, "hour_label": service_hour(int(c["service_hour"]))}
        for c in kpis.headway_route_hour(con, src, grp, day)
        if c["route_id"] in shown
    ]
    figures = []
    takeaway = None
    if row is not None:
        irregular = max(0.0, 1 - row["regular_share"] - row["bunched_share"] - row["gap_share"])
        figures = [
            _figure("headways", "Headways observed", row["headways"], count(row["headways"])),
            _figure(
                "regular",
                "Regular",
                row["regular_share"],
                pct(row["regular_share"]),
                "Within ±20 % of the scheduled headway.",
                badge=dict(HEADWAY_REGULAR_BADGE),
            ),
            _figure(
                "bunched",
                "Bunched",
                row["bunched_share"],
                pct(row["bunched_share"]),
                "At most 25 % of the scheduled headway.",
                badge=bunching_badge(row["bunched_share"]),
            ),
            _figure(
                "gaps",
                "Gaps",
                row["gap_share"],
                pct(row["gap_share"]),
                "At least twice the scheduled headway.",
                badge=gapping_badge(row["gap_share"]),
            ),
            _figure(
                "irregular",
                "Irregular",
                irregular,
                pct(irregular),
                "Every other headway: off schedule, not extreme.",
                badge=dict(HEADWAY_IRREGULAR_BADGE),
            ),
        ]
        takeaway = (
            f"{pct(row['regular_share'])} of {count(row['headways'])} observed headways kept to "
            f"the timetable, while {pct(row['bunched_share'])} bunched together and "
            f"{pct(row['gap_share'])} left long gaps."
        )
    return {
        "day": day,
        "day_label": day_label(day),
        "takeaway": takeaway,
        "summary": row,
        "figures": figures,
        "routes": routes,
        "cells": cells,
        "definitions": HEADWAY_DEFINITIONS,
    }


MISSING_DEFINITIONS = (
    "Each scheduled trip on a route the feed carries that day gets the **first** outcome "
    "that applies:\n"
    "1. **Delivered (most stops seen):** reported, and at least half of its intermediate stops "
    "observed as passed.\n"
    "2. **Could not be judged:** not seen delivered, and the feed could not tell: the trip's "
    "scheduled time falls outside the snapshots read or overlaps a feed outage longer than 5 "
    "minutes.\n"
    "3. **Never reported:** the trip never appeared in the feed under any matching rule. This is "
    "strong evidence that it did not run, not proof: a trip that ran under an ID the timetable "
    "does not know is counted here.\n"
    "4. **Announced, never moved:** reported, but no stop was ever passed and (for buses) no GPS "
    "arrival at the last stop.\n"
    "5. **Partly observed:** seen running, but fewer than half of its stops observed as passed; "
    "the trip may have run in full while the feed missed stops.\n\n"
    "**Not seen running** = (never reported + announced, never moved) ÷ (scheduled − could not "
    "be judged). Route ranking: routes "
    f"with at least {MIN_TRIPS} observable trips."
)


def missing_trips(con: Con, src: Source, grp: str, day: str) -> Row:
    """BR3: every scheduled trip's outcome, the least delivered routes, and the subway caveat."""
    row = _pick(kpis.delivery_overview(con, src), grp=grp, service_date=day)
    caveat = _subway_caveat(con, src, day) if grp == "subway" else None
    figures, outcomes = [], []
    takeaway = None
    if row is not None:
        observable = row["scheduled"] - row["unknown"]
        figures = [
            _figure("scheduled", "Scheduled trips", row["scheduled"], count(row["scheduled"])),
            _figure(
                "not_delivered",
                "Not seen running",
                row["not_delivered_share"],
                pct(row["not_delivered_share"]),
                "Never reported + announced but never moved, as a share of the trips the feed "
                "could observe (trips that could not be judged excluded).",
                f"of {count(observable)} observable trips",
                badge=not_delivered_badge(row["not_delivered_share"]),
            ),
            _figure(
                "unknown",
                "Could not be judged",
                row["unknown"],
                count(row["unknown"]),
                "Trips whose scheduled time fell outside the snapshots read or inside a feed "
                "outage.",
                badge=dict(UNKNOWN_TRIPS_BADGE),
            ),
        ]
        outcomes = [
            {
                "key": key,
                "outcome": label,
                "trips": int(row[key]),
                "order": i,
                "not_delivered": key in NOT_DELIVERED,
            }
            for i, (key, label) in enumerate(OUTCOMES)
        ]
        base_sentence = (
            f"{pct(row['not_delivered_share'])} of {count(observable)} observable scheduled "
            f"trips were not seen running ({count(row['missing'])} never reported, "
            f"{count(row['not_run'])} announced without moving)"
        )
        takeaway = (
            f"{base_sentence}; read with care because {caveat['display']} of real-time trips had "
            "unmatched IDs."
            if caveat is not None
            else f"{base_sentence}."
        )
    return {
        "day": day,
        "day_label": day_label(day),
        "takeaway": takeaway,
        "summary": row,
        "figures": figures,
        "outcomes": outcomes,
        "caveat": caveat,
        "routes": kpis.least_delivered_routes(con, src, grp, day, limit=RANKED_ROUTES),
        "min_trips": MIN_TRIPS,
        "definitions": MISSING_DEFINITIONS,
    }


# --- scorecards: routes (BR5) and stops (BR8) -------------------------------------------------

SCORECARD_DEFINITIONS = (
    "- **On-time share:** arrivals at intermediate stops within −1 / +5 min of the "
    "timetable, pooled over both service days (same definition as On-time performance).\n"
    "- **95 % interval:** a bootstrap that resamples whole **trips** 200 times (stops of one "
    "trip are not independent). The resampling weights come from a hash, so the result is "
    "exactly reproducible; the Spark result equals the independent DuckDB reference.\n"
    "- **Plausible ranks:** the rank a route gets in 95 % of the resamples.\n"
    f"- **Ranked:** routes with at least {MIN_ROUTE_TRIPS} trips and 10 arrivals; the others "
    "are left unranked rather than ranked on noise."
)


def _rank_interval(row: Row) -> str:
    low, high = row["rank_low"], row["rank_high"]
    return "—" if low is None or high is None else f"{int(low)} to {int(high)}"


def route_scorecards(con: Con, src: Source, grp: str) -> Row:
    """BR5: ranked routes with intervals; the least and most punctual for the chart."""
    rows = [{**r, "rank_interval": _rank_interval(r)} for r in kpis.route_scorecards(con, src, grp)]
    ranked = [r for r in rows if r["sufficient"]]  # by rank: most punctual first
    return {
        "ranked": ranked,
        "unranked": [r for r in rows if not r["sufficient"]],
        # Stable sorts: routes with equal shares keep their rank order.
        "least": sorted(ranked[-SHOWN_ROUTES:], key=lambda r: r["on_time_share"]),
        "most": sorted(ranked[:SHOWN_ROUTES], key=lambda r: -r["on_time_share"]),
        "caption": (
            f"Ranked among {len(ranked)} {GROUPS[grp]} routes with at least {MIN_ROUTE_TRIPS} "
            "trips and 10 arrivals. Where two routes' lines overlap, the data cannot tell them "
            "apart."
        ),
        "definitions": SCORECARD_DEFINITIONS,
    }


STOP_DEFINITIONS = (
    "- **Arrivals:** inferred arrivals of this route at this stop (see On-time performance), "
    "pooled over both service days.\n"
    "- **95 % interval:** the Wilson score interval. Arrivals in the same hour share "
    "traffic, so the interval is somewhat optimistic.\n"
    "- **Typical delay** is the median; **bad-day delay** is the 90th percentile "
    "(negative = early)."
)


def stop_routes(con: Con, src: Source, grp: str) -> list[str]:
    """BR8: routes with at least one stop-hour observed often enough to be scored."""
    return kpis.stop_routes(con, src, grp)


def route_stops(con: Con, src: Source, grp: str, route_id: str) -> list[Row]:
    """BR8: a route's stops, labelled with their name when one is known."""
    return [
        {
            **stop,
            "label": f"{stop['stop_name']} ({stop['stop_id']})"
            if stop["stop_name"]
            else stop["stop_id"],
        }
        for stop in kpis.route_stops(con, src, grp, route_id)
    ]


def _stop_summary(hours: list[Row]) -> Row:
    """Hours at one stop plus their totals: arrivals, on time over all hours, hours scored."""
    labelled = [
        {
            **h,
            "hour_label": service_hour(int(h["service_hour"])),
            "hour_short": service_hour_short(int(h["service_hour"])),
        }
        for h in hours
    ]
    arrivals = sum(int(h["events"]) for h in labelled)
    on_time_count = sum(int(h["on_time"]) for h in labelled)
    share = on_time_count / arrivals if arrivals else None
    scored = sum(bool(h["sufficient"]) for h in labelled)
    return {
        "hours": labelled,
        "figures": [
            _figure("arrivals", "Arrivals observed", arrivals, count(arrivals)),
            _figure("on_time", "On time, all hours", share, pct(share)),
            _figure(
                "scored_hours",
                "Hours with enough data",
                scored,
                f"{scored} of {len(labelled)}",
                f"Hours with at least {MIN_CELL_EVENTS} arrivals over both days.",
            ),
        ],
    }


def stop_detail(
    con: Con, src: Source, grp: str, route_id: str, direction_id: int | None, stop_id: str
) -> Row:
    """BR8: one stop of one route, hour by hour, with its totals."""
    return _stop_summary(kpis.stop_hours(con, src, grp, route_id, direction_id, stop_id))


def route_stop_details(con: Con, src: Source, grp: str, route_id: str) -> list[Row]:
    """BR8: every stop of a route with its hours and totals (one query; the static export)."""
    hours: dict[tuple[Any, str], list[Row]] = {}
    for row in kpis.route_stop_hours(con, src, grp, route_id):
        key = (row.pop("direction_id"), row.pop("stop_id"))
        hours.setdefault(key, []).append(row)
    return [
        {**stop, **_stop_summary(hours.get((stop["direction_id"], stop["stop_id"]), []))}
        for stop in route_stops(con, src, grp, route_id)
    ]


MAP_WORST = 10  # the map's text summary names this many least reliable stops

MAP_DEFINITIONS = (
    "- **Arrivals at a stop:** inferred arrivals of every route that serves the stop, all "
    "hours, both service days pooled (see On-time performance for how an arrival is "
    "inferred).\n"
    "- **On time:** the share of those arrivals at most 1 min early and at most 5 min late.\n"
    "- **Stop ID:** the MTA's own identifier. Each direction of a street has its own stop and "
    "its own ID.\n"
    f"- **Scored:** stops with at least {MIN_CELL_EVENTS} arrivals; the others are drawn "
    "hollow and not compared.\n"
    "- **Background:** bus and subway route shapes from the MTA static timetables, drawn "
    "without map tiles."
)


def stop_map(con: Con, src: Source, grp: str) -> Row:
    """BR8 map: located stops, least reliable sufficient stops first, then the thinly observed.

    A stop is sufficient with at least MIN_CELL_EVENTS arrivals pooled over all routes and hours
    (the same bar as one stop-hour on the stop reliability page).
    """
    raw_stops = [
        {
            **s,
            "sufficient": s["events"] >= MIN_CELL_EVENTS,
            "label": f"{s['stop_name']} ({s['stop_id']})" if s["stop_name"] else s["stop_id"],
            "display": pct(s["on_time_share"]),
        }
        for s in kpis.stop_map(con, src, grp)
    ]
    scored_shares = [
        float(s["on_time_share"])
        for s in raw_stops
        if s["sufficient"] and s["on_time_share"] is not None
    ]
    median_share = round(statistics.median(scored_shares), 4) if scored_shares else None
    band_counts = [0] * len(STOP_MAP_BANDS)
    stops = []
    for s in raw_stops:
        band_id = stop_map_band_index(s["on_time_share"], s["sufficient"])
        if band_id >= 0:
            band_counts[band_id] += 1
        stops.append(
            {
                **s,
                "band": band_id,
                "delta_pts": stop_map_delta_pts(s["on_time_share"], median_share, s["sufficient"]),
            }
        )
    ordered = sorted(stops, key=lambda s: (not s["sufficient"], s["on_time_share"], s["stop_id"]))
    worst = [s for s in ordered if s["sufficient"]][:MAP_WORST]
    return {
        "stops": ordered,
        "worst": worst,
        "sufficient": sum(s["sufficient"] for s in stops),
        "min_events": MIN_CELL_EVENTS,
        "stop_median_share": median_share,
        "stop_median_display": pct(median_share),
        "bands": [dict(b) for b in STOP_MAP_BANDS],
        "thin_band": dict(STOP_MAP_THIN_BAND),
        "band_counts": band_counts,
        "definitions": MAP_DEFINITIONS,
        "summary": (
            f"{len(stops):,} located stops, {sum(s['sufficient'] for s in stops):,} with at least "
            f"{MIN_CELL_EVENTS} arrivals over both days. Least reliable: "
            + "; ".join(f"{s['label']} {s['display']}" for s in worst)
            + "."
        ),
    }


def hero_map(con: Con, src: Source) -> Row:
    """Every located stop of both modes binned into a grid, for the overview's map graphic.

    Each cell pools its stops' arrivals and on-time arrivals (sums of validated columns), so a
    cell's share is arrivals-weighted; cells under MIN_CELL_EVENTS arrivals are flagged thin.
    """
    lat_step, lon_step = HERO_CELL
    cells: dict[tuple[int, int], list[int]] = {}
    for grp in GROUPS:
        for s in kpis.stop_map(con, src, grp):
            key = (round(s["lat"] / lat_step), round(s["lon"] / lon_step))
            cell = cells.setdefault(key, [0, 0, 0])
            cell[0] += int(s["events"])
            cell[1] += int(s["on_time"])
            cell[2] += 1
    rows = [
        {
            "lat": round(i * lat_step, 4),
            "lon": round(j * lon_step, 4),
            "events": events,
            "stops": stops,
            "on_time_share": round(on_time / events, 4) if events else None,
            "sufficient": events >= MIN_CELL_EVENTS,
        }
        for (i, j), (events, on_time, stops) in sorted(cells.items())
    ]
    located = sum(stops for _, _, stops in cells.values())
    return {
        "cells": rows,
        "cell_m": 670,
        "stops": located,
        "caption": (
            f"{located:,} bus and subway stops in {len(rows):,} cells of "
            "about 670 m, coloured by the share of their inferred arrivals that were on time, "
            "both days pooled. Grey: cells with fewer than "
            f"{MIN_CELL_EVENTS} arrivals."
        ),
    }


def findings(con: Con, src: Source) -> list[Row]:
    """Four results worth reading first, each stated with its numbers and the page behind it."""
    pooled = {}
    for grp in GROUPS:
        rows = [r for r in kpis.otp_overview(con, src) if r["grp"] == grp]
        rows = [r for r in rows if r["scope"] == "all_stops"]
        events = sum(r["events"] for r in rows)
        pooled[grp] = (sum(r["on_time_share"] * r["events"] for r in rows) / events, events)
    all_bus_hours = [
        {
            "hour": int(h["service_hour"]),
            "hour_label": service_hour(int(h["service_hour"])),
            "events": int(h["events"]),
            "share": h["on_time_share"],
            "display": pct(h["on_time_share"]),
            "sufficient": h["events"] >= HOURLY_MIN_EVENTS,
        }
        for h in kpis.hourly_on_time(con, src, "bus")
    ]
    hours = [h for h in all_bus_hours if h["sufficient"]]
    worst_hour = min(hours, key=lambda h: (h["share"], h["hour"]))
    best_hour = max(hours, key=lambda h: (h["share"], -h["hour"]))
    ranked = route_scorecards(con, src, "bus")["ranked"]
    sorted_shares = sorted(float(r["on_time_share"]) for r in ranked)
    last = ranked[-1]
    late = next(v for v in early_warning(con, src, "bus")["verdicts"] if v["outcome"] == "late")
    mode_gap_label = f"{pts_delta(pooled['subway'][0] - pooled['bus'][0])} pt gap"
    hour_drop_label = (
        f"{pts_delta(best_hour['share'] - worst_hour['share']).lstrip('+')} pt drop from peak"
    )
    late_passed = bool(late.get("passed"))
    return [
        {
            "key": "modes",
            "kicker": "Bus vs subway",
            "value": pct(pooled["subway"][0]),
            "badge": _badge(mode_gap_label, "attention"),
            "headline": (
                f"{pct(pooled['subway'][0])} of subway arrivals were on time, against "
                f"{pct(pooled['bus'][0])} of bus arrivals."
            ),
            "detail": (
                f"Both days pooled: {count(pooled['subway'][1])} subway and "
                f"{count(pooled['bus'][1])} bus inferred arrivals at intermediate stops."
            ),
            "stats": {
                "subway_share": pooled["subway"][0],
                "subway_display": pct(pooled["subway"][0]),
                "subway_events": int(pooled["subway"][1]),
                "bus_share": pooled["bus"][0],
                "bus_display": pct(pooled["bus"][0]),
                "bus_events": int(pooled["bus"][1]),
            },
            "page": "on-time",
        },
        {
            "key": "hours",
            "kicker": "Time of day",
            "value": pct(worst_hour["share"]),
            "badge": _badge(hour_drop_label, "attention"),
            "headline": (
                f"Bus punctuality was lowest at {worst_hour['hour_label']} "
                f"({worst_hour['display']}) and highest at "
                f"{best_hour['hour_label']} ({best_hour['display']})."
            ),
            "detail": (
                f"Hours of the service day (scheduled time) with at least "
                f"{HOURLY_MIN_EVENTS:,} arrivals, both days pooled."
            ),
            "stats": {
                "worst_hour": worst_hour["hour"],
                "worst_hour_label": worst_hour["hour_label"],
                "worst_share": worst_hour["share"],
                "worst_display": worst_hour["display"],
                "best_hour": best_hour["hour"],
                "best_hour_label": best_hour["hour_label"],
                "best_share": best_hour["share"],
                "best_display": best_hour["display"],
                "points": [h for h in all_bus_hours if h["hour"] <= 23 and h["share"] is not None],
            },
            "page": "on-time",
        },
        {
            "key": "route",
            "kicker": "Least punctual route",
            "value": pct(last["on_time_share"]),
            "badge": dict(FINDING_ROUTE_BADGE),
            "headline": (
                f"Route {last['route_id']} ranked last of {len(ranked)} bus routes: "
                f"{pct(last['on_time_share'])} on time."
            ),
            "detail": (
                f"95 % interval {pct(last['ci_low'])} to {pct(last['ci_high'])}, "
                f"plausible ranks {last['rank_interval']}, from {count(last['events'])} arrivals."
            ),
            "stats": {
                "median": _linear_quantile(sorted_shares, 0.5),
                "q25": _linear_quantile(sorted_shares, 0.25),
                "q75": _linear_quantile(sorted_shares, 0.75),
            },
            "page": "scorecards",
        },
        {
            "key": "warning",
            "kicker": "Early warning",
            "value": late.get("f1_display", "—"),
            "badge": _badge(
                "Passed checks" if late_passed else "Did not pass",
                "pass" if late_passed else "fail",
            ),
            "headline": (
                f"Halfway through a bus trip, a simple rule predicted a late finish with F1 "
                f"{late.get('f1_display')} against the baseline's {late.get('baseline_f1_display')}"
                f" on a held-out day: {late.get('verdict')}."
            ),
            "detail": (
                f"Precision {late.get('precision_display')}, recall {late.get('recall_display')}; "
                "rules were tuned on the other day only."
            ),
            "page": "early-warning",
        },
    ]


def pipeline(folder: Path) -> Row:
    """The pipeline's scale and checks, read only from the evidence files of the snapshot."""
    replay = evidence.load(folder, "replay-report")
    integrity, parity = evidence.source_integrity(folder), evidence.golden_parity(folder)
    gold_run = evidence.load(folder, "gold-kpis")
    layers = {layer["layer"]: layer for layer in parity["layers"]}
    silver = layers.get("silver", {"tables": []})
    stop_events = next((t["rows"] for t in silver["tables"] if t["table"] == "stop_events"), None)
    tests = evidence.tests(folder)
    return {
        "messages": count(sum(f["messages"] for f in replay["feeds"])) if replay else None,
        "archive_rows": (
            count(sum(f["archive_rows"] for f in integrity["feeds"]))
            if integrity["available"]
            else None
        ),
        "stop_events": count(stop_events),
        "silver": f"{layers['silver']['passed']} / {layers['silver']['total']}"
        if "silver" in layers
        else None,
        "gold": f"{layers['gold']['passed']} / {layers['gold']['total']}"
        if "gold" in layers
        else None,
        "gold_seconds": f"{gold_run['elapsed_s']:,.0f} s" if gold_run else None,
        "tests": f"{tests['passed']:,} / {tests['ran']:,}" if tests["available"] else None,
    }


# --- diagnostics: delay attribution (BR4), early warning (BR6) ---------------------------------

DELAY_DEFINITIONS = (
    "- **Segment:** two consecutive observed stops of one trip, recorded by the same "
    "vehicle. No segment crosses a hand-off to another vehicle.\n"
    "- **Excess:** observed travel time minus scheduled travel time (negative = time "
    "gained). Arrival-to-arrival, so a segment includes the dwell at its first stop: the "
    "feed does not report departures, so dwell and running time cannot be separated.\n"
    "- **Attribution:** final delay = delay at the first observed stop + the sum of the "
    "excesses; exact in whole seconds for every trip.\n"
    "- The ranking uses adjacent stops only and leaves out negative observed travel times "
    "(a late prediction at the earlier stop, 1 to 2 % of segments)."
)


def delay(con: Con, src: Source, grp: str, day: str) -> Row:
    """BR4: how much of a trip's final delay it inherited and how much it gained en route."""
    row = _pick(kpis.delay_overview(con, src), grp=grp, service_date=day)
    if row is None:
        return {
            "day": day,
            "day_label": day_label(day),
            "takeaway": None,
            "summary": None,
            "figures": [],
            "caption": None,
            "definitions": DELAY_DEFINITIONS,
        }
    inherited_display = minutes(row["mean_inherited_delay_s"])
    gained_display = minutes(row["mean_gained_delay_s"])
    final_display = minutes(row["mean_final_delay_s"])
    return {
        "day": day,
        "day_label": day_label(day),
        "takeaway": (
            f"A typical trip reached its first observed stop {inherited_display} late and lost "
            f"another {gained_display} along the way, finishing {final_display} late."
        ),
        "summary": row,
        "figures": [
            _figure(
                "inherited",
                "Delay at first observed stop",
                row["mean_inherited_delay_s"],
                inherited_display,
                "Mean over trips (one row per trip and vehicle).",
            ),
            _figure(
                "gained",
                "Delay gained en route",
                row["mean_gained_delay_s"],
                gained_display,
                "Mean of the sum of segment excesses: observed minus scheduled travel time.",
            ),
            _figure(
                "final",
                "Delay at last observed stop",
                row["mean_final_delay_s"],
                final_display,
            ),
        ],
        "caption": (
            f"{row['trip_vehicles']:,} trips. The split is exact for every one of them "
            f"({row['attribution_mismatches']} trips where inherited + gained ≠ final)."
        ),
        "definitions": DELAY_DEFINITIONS,
    }


def costly_segments(con: Con, src: Source, grp: str) -> Row:
    """BR4: the stop-to-stop segment-hours that lose the most time, pooled over both days."""
    rows = [
        {
            **r,
            "hour_label": service_hour(int(r["service_hour"])),
            "segment": (
                f"{service_hour(int(r['service_hour']))}, {r['route_id']}: "
                f"{r['from_name']} to {r['to_name']}"
            ),
        }
        for r in kpis.costly_segments(con, src, grp, MIN_SEGMENTS, limit=RANKED_ROUTES)
    ]
    return {
        "segments": rows,
        "min_segments": MIN_SEGMENTS,
        "caption": (
            f"Pooled over both service days; segment-hours with at least {MIN_SEGMENTS} "
            "observations, ranked by their median excess over the timetable."
        ),
    }


WARNING_DEFINITIONS = (
    "- **Decision point:** the first observed stop at or past the middle of the trip that "
    "is followed by at least one more observed stop of the same vehicle.\n"
    "- **Late rule:** current delay + ½ × delay trend × scheduled time still to go > 5 min. "
    "*Baseline:* current delay > 5 min. *Outcome:* delay at the last observed stop > 5 min.\n"
    "- **Bunching rule:** current headway ≤ ½ of the scheduled headway. *Baseline:* already "
    "classified bunched. *Outcome:* bunched at any later stop.\n"
    "- **Precision:** of the trips a rule warned about, the share that really ended late (or "
    "really got bunched). **Recall:** of the trips that really ended late (or got bunched), "
    "the share the rule warned about. **F1** combines the two into one score from 0 to 1; "
    "higher is better.\n"
    f"- Rules and thresholds were tuned on {day_label(DEVELOPMENT_DAY)} only; "
    f"{day_label(HELD_OUT_DAY)} is held out. Acceptance, declared before the held-out day "
    "was computed: the rule beats its baseline on F1 with precision ≥ "
    f"{pct(MIN_PRECISION, 0)}.\n"
    "- The decision population uses whole-day knowledge (a later observed stop must exist), "
    "so absolute precision is optimistic for live use; rule and baseline are judged on the "
    "same population, so their comparison is fair."
)


def early_warning(con: Con, src: Source, grp: str) -> Row:
    """BR6: did each rule beat its baseline on the held-out day, and both days side by side."""
    rows = [r for r in kpis.warning_summary(con, src) if r["grp"] == grp]
    verdicts = []
    for outcome, title in (("late", "Ends late"), ("bunched", "Gets bunched")):
        held = {
            r["method"]: r
            for r in rows
            if r["service_date"] == HELD_OUT_DAY and r["outcome"] == outcome
        }
        rule, base = held.get("rule"), held.get("baseline")
        if rule is None or base is None:
            verdicts.append({"outcome": outcome, "title": title, "available": False})
            continue
        passed = bool(rule["f1"] > base["f1"] and rule["precision"] >= MIN_PRECISION)
        verdicts.append(
            {
                "outcome": outcome,
                "title": title,
                "available": True,
                "passed": passed,
                "verdict": "passed" if passed else "did not pass",
                "f1": rule["f1"],
                "f1_display": decimal(rule["f1"]),
                "baseline_f1": base["f1"],
                "baseline_f1_display": decimal(base["f1"]),
                "precision": rule["precision"],
                "precision_display": pct(rule["precision"], 0),
                "recall": rule["recall"],
                "recall_display": pct(rule["recall"], 0),
                "decisions": int(rule["decisions"]),
                "positives": int(rule["positives"]),
                "caption": (
                    f"{int(rule['decisions']):,} trips judged, {int(rule['positives']):,} "
                    f"actually {outcome}."
                ),
            }
        )
    comparison = [
        {
            **r,
            "day": f"{day_label(r['service_date'])} "
            f"({'tuning' if r['service_date'] == DEVELOPMENT_DAY else 'held out'})",
            "Method": {"rule": "Rule", "baseline": "Baseline"}[r["method"]],
        }
        for r in rows
    ]
    return {
        "held_out_day": HELD_OUT_DAY,
        "held_out_label": day_label(HELD_OUT_DAY),
        "development_day": DEVELOPMENT_DAY,
        "min_precision": MIN_PRECISION,
        "min_precision_display": pct(MIN_PRECISION, 0),
        "verdicts": verdicts,
        "comparison": comparison,
        "dispatcher": warning_list(con, src, grp, HELD_OUT_DAY),
        "definitions": WARNING_DEFINITIONS,
    }


WARNING_MIN_DECISIONS = 30  # a route is ranked with at least this many decisions on the day
WARNING_EXAMPLES = 3  # trips shown per kind (warning came true, false alarm)


def _came_true(hits: int, warned: int) -> str:
    """'318 of 412 came true (77 %)', or a dash when nothing was warned."""
    return f"{hits:,} of {warned:,} came true ({pct(hits / warned, 0)})" if warned else "—"


def _clock(seconds: int) -> str:
    """Seconds after GTFS time zero as HH:MM; hours past 23 carry '(+1)'."""
    hr, mn = seconds // 3600, seconds % 3600 // 60
    if hr >= 24:
        return f"{hr - 24:02d}:{mn:02d} (+1)"
    return f"{hr:02d}:{mn:02d}"


def warning_list(con: Con, src: Source, grp: str, day: str) -> Row:
    """BR6 for the dispatcher (U1): where and when the rules raised warnings on one replayed
    day, how many came true, and example trips the late rule flagged."""
    if not src.has("warning_decisions"):
        return {"available": False}
    base = day_base(day)

    def counts(r: Row) -> Row:
        return {
            **r,
            "warnings": int(r["warned_late"] + r["warned_bunched"]),
            "late_display": _came_true(int(r["late_hits"]), int(r["warned_late"])),
            "bunched_display": _came_true(int(r["bunched_hits"]), int(r["warned_bunched"])),
        }

    routes = [
        counts(r)
        for r in kpis.warning_routes(con, src, grp, day, WARNING_MIN_DECISIONS, RANKED_ROUTES)
    ]
    # Hours in which the rules raised no warning carry nothing for the dispatcher.
    hours = [counts(r) for r in kpis.warning_hours(con, src, grp, day, base)]
    hours = [h for h in hours if h["warnings"]]
    for h in hours:
        h["label"] = service_hour(int(h["service_hour"]))
        h["hour_label"] = h["label"]
    # Bar lengths relative to the longest bar of each list, so the frontends only draw them.
    for rows in (routes, hours):
        top = max((r["warnings"] for r in rows), default=0)
        for r in rows:
            r["bar"] = round(r["warnings"] / top, 4) if top else 0.0
    examples = []
    for came_true in (True, False):
        for r in kpis.warning_examples(con, src, grp, day, came_true, WARNING_EXAMPLES):
            examples.append(
                {
                    **r,
                    "kind": "warning came true" if came_true else "false alarm",
                    "stop": (
                        f"{r['stop_name']} ({r['decision_stop']})"
                        if r["stop_name"]
                        else r["decision_stop"]
                    ),
                    "time": _clock(int(r["decision_time"]) - base),
                    "delay_display": minutes(r["delay_s"]),
                    "projected_display": minutes(r["projected_delay_s"]),
                    "outcome": "ended late" if r["late"] else "did not end late",
                }
            )
    return {
        "available": True,
        "day": day,
        "day_label": day_label(day),
        "min_decisions": WARNING_MIN_DECISIONS,
        "routes": routes,
        "hours": hours,
        "examples": examples,
        "routes_caption": (
            f"The {len(routes)} routes with the most warnings on {day_label(day)}, among routes "
            f"with at least {WARNING_MIN_DECISIONS} trips judged. Warnings count late and "
            "bunching warnings separately, so one trip can carry both. A warning came true when "
            "the trip really ended late (or really got bunched later)."
        ),
        "hours_caption": (
            "Warnings raised in each hour of the service day, by the time of the decision point "
            "(halfway through the trip); hours without a warning are left out. Hours marked (+1) "
            "continue the same service day after midnight."
        ),
        "examples_caption": (
            "Trips the late rule warned about, one per route, highest projected delay first: "
            f"{WARNING_EXAMPLES} whose warning came true and {WARNING_EXAMPLES} false alarms. "
            "Delays are at the decision point; the projection adds half the delay trend over "
            "the scheduled time still to go."
        ),
    }


# --- data quality: feed health (BR7) and validation evidence -----------------------------------

FEED_DEFINITIONS = (
    "- Lower is better for every check. A check with no data counts as **failed** rather "
    "than disappearing from the score.\n"
    "- Snapshot and GPS checks use the local calendar day of the snapshot; trip and stop "
    "checks use the service day.\n"
    "- *Missed polls* is measured on the archive's fetch times, not on the feed's own "
    "timestamps, which drift with the feed's publication lag.\n"
    "- p99 = 99th percentile."
)


def _check_name(metric: str) -> str:
    return FEED_CHECKS.get(metric, (metric, "", ""))[0]


def feed_days(con: Con, src: Source) -> list[str]:
    """Days with feed-quality scores, in order."""
    return list(dict.fromkeys(r["day"] for r in kpis.feed_scores(con, src)))


def feed_health(con: Con, src: Source, day: str) -> Row:
    """BR7: each feed's conformance score on a day, and every check against its threshold."""
    scores = kpis.feed_scores(con, src)
    feeds = []
    for feed, label in FEEDS.items():
        row = _pick(scores, feed=feed, day=day)
        if row is None:
            continue
        failed = row["failed_checks"]
        names = [_check_name(m) for m in failed.split(", ")] if failed else []
        checks = [
            {
                **check,
                "result": "Pass" if check["passed"] else "Fail",
                "check": _check_name(check["metric"]),
                "measured": check_value(
                    check["value"], FEED_CHECKS.get(check["metric"], ("", "", ""))[2]
                ),
                "threshold_display": check_threshold(
                    check["threshold"], FEED_CHECKS.get(check["metric"], ("", "", ""))[2]
                ),
                "description": FEED_CHECKS.get(check["metric"], ("", check["metric"], ""))[1],
            }
            for check in kpis.feed_checks(con, src, feed, day)
        ]
        passed_count = int(row["passed"])
        total_count = int(row["checks"])
        failed_count = total_count - passed_count
        feeds.append(
            {
                "feed": feed,
                "label": label,
                "score": row["score"],
                "display": score(row["score"]),
                "help": f"{passed_count} of {total_count} checks passed",
                "passed": passed_count,
                "total": total_count,
                "failed_count": failed_count,
                "badge": feed_health_card_badge(failed_count, total_count),
                "status_badge": feed_health_status_badge(failed_count),
                "failed": names,
                "checks": checks,
            }
        )
    return {
        "day": day,
        "day_label": day_label(day),
        "feeds": feeds,
        "definitions": FEED_DEFINITIONS,
    }


def validation(folder: Path) -> Row:
    """The evidence that the pipeline processed the data correctly, from committed result files."""
    integrity = evidence.source_integrity(folder)
    table: list[Row] = []
    if integrity["available"]:
        feeds = integrity["feeds"]

        def yes(flag: bool) -> str:
            return "Yes" if flag else "No"

        checks: list[tuple[str, list[str]]] = [
            ("Snapshots replayed", [count(f["snapshots"]) for f in feeds]),
            ("Archive rows", [count(f["archive_rows"]) for f in feeds]),
            (
                "Kafka messages sent (incl. 1 marker per snapshot)",
                [count(f["messages"]) for f in feeds],
            ),
            (
                "All acknowledged and read back",
                [yes(f["read_back_equal"] and f["all_acknowledged"]) for f in feeds],
            ),
            (
                "Sampled snapshots identical to the archive",
                [
                    f"{f['fidelity_sampled'] - f['fidelity_mismatched']} / {f['fidelity_sampled']}"
                    for f in feeds
                ],
            ),
            ("Silver rows", [count(f["silver_rows"]) for f in feeds]),
            ("Silver rows = archive rows", [yes(f["rows_equal"]) for f in feeds]),
            (
                "Duplicates / late / dead-lettered",
                [
                    " / ".join(str(f[k]) for k in ("duplicates", "late", "dead_lettered"))
                    for f in feeds
                ],
            ),
            ("Message counts balance", [yes(f["balanced"]) for f in feeds]),
        ]
        table = [
            {"Check": name}
            | {EVIDENCE_FEEDS.get(f["feed"], f["feed"]): values[i] for i, f in enumerate(feeds)}
            for name, values in checks
        ]
    parity = evidence.golden_parity(folder)
    return {
        "datasets": [
            {"Dataset": name, "Content": content, "Source": source}
            for name, content, source in DATASETS
        ],
        "integrity": integrity,
        "integrity_table": table,
        "parity": parity,
        "parity_tables": [
            {
                "Layer": layer["layer"].title(),
                "Table": t["table"],
                "Result": "Equal" if t["ok"] else "Differs",
                "Rows compared": t["rows"],
            }
            for layer in parity["layers"]
            for t in layer["tables"]
        ],
        "policy": evidence.tolerance_policy(folder),
        "tests": evidence.tests(folder),
    }
