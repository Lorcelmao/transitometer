"""Page views shared by both frontends: the data, rules, labels and display strings of each page.

A view is a pure function of a connection, a source and the page's filters. It returns plain,
JSON-serialisable data: raw rows for charts and tables, display strings (serve/format.py) for every
headline figure, and the page's metric definitions. The Streamlit app renders views directly;
`python tasks.py web-data` writes them as JSON for the Next.js site. Neither frontend defines a
threshold, ranking size, pass rule, label or definition of its own, so both show the same numbers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

from transitometer.serve import evidence, kpis
from transitometer.serve.format import (
    check_threshold,
    check_value,
    count,
    day_label,
    decimal,
    minutes,
    pct,
    score,
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

GROUPS = {"bus": "MTA Bus", "subway": "NYC Subway (lines 1–7, S)"}
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
    ("NYC Subway trip updates", "Lines 1–7 and S", "gtfsrt.io archive (MTA feed)"),
    ("MTA static timetables (GTFS)", "Scheduled trips and stop times", "MTA"),
]


def _figure(
    key: str,
    label: str,
    value: Any,
    display: str,
    help: str | None = None,
    basis: str | None = None,
) -> Row:
    """A headline number: raw value for charts and tests, display string for both frontends, and
    the sample it is computed on (`basis`, for example "of 1,379,432 inferred arrivals")."""
    return {
        "key": key,
        "label": label,
        "value": value,
        "display": display,
        "help": help,
        "basis": basis,
    }


def _pick(rows: list[Row], **match: Any) -> Row | None:
    return next((r for r in rows if all(r.get(k) == v for k, v in match.items())), None)


# --- overview --------------------------------------------------------------------------------


def overview(con: Con, src: Source, grp: str, day: str) -> Row:
    """The day at a glance: punctuality, bunching, delivery and feed quality of one mode."""
    otp = _pick(kpis.otp_overview(con, src), grp=grp, service_date=day, scope="all_stops")
    heads = _pick(kpis.headway_overview(con, src), grp=grp, service_date=day)
    trips = _pick(kpis.delivery_overview(con, src), grp=grp, service_date=day)
    feed = _pick(kpis.feed_scores(con, src), feed=f"{grp}_tu", day=day)
    observable = trips["scheduled"] - trips["unknown"] if trips else None
    figures = [
        _figure(
            "on_time",
            "Inferred arrivals on time",
            otp and otp["on_time_share"],
            pct(otp["on_time_share"]) if otp else "—",
            "Share of inferred arrivals at intermediate scheduled stops that were at most 1 min "
            "early and at most 5 min late (the MTA's on-time band).",
            f"of {count(otp['events'])} inferred arrivals" if otp else None,
        ),
        _figure(
            "bunched",
            "Headways bunched",
            heads and heads["bunched_share"],
            pct(heads["bunched_share"]) if heads else "—",
            "Share of observed gaps between consecutive vehicles that were at most a quarter of "
            "the scheduled gap: vehicles arriving in clumps.",
            f"of {count(heads['headways'])} observed headways" if heads else None,
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
        ),
        _figure(
            "feed_score",
            "Feed quality score",
            feed and feed["score"],
            score(feed["score"]) if feed else "—",
            "Share of the feed's data-quality checks that passed (trip-update feed of this "
            "mode, this day).",
            f"{feed['passed']} of {feed['checks']} checks passed" if feed else None,
        ),
    ]
    hours = [
        {
            **h,
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
        "figures": figures,
        "hours": hours,
        "hourly_min_events": HOURLY_MIN_EVENTS,
        "caveat": _subway_caveat(con, src, day) if grp == "subway" else None,
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
            "display": " · ".join(
                f"{layer['layer'].title()} {layer['passed']} / {layer['total']}"
                for layer in parity["layers"]
            ),
        },
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
        {**cell, "scored": cell["events"] >= MIN_EVENTS}
        for cell in kpis.otp_route_hour(con, src, grp, day)
        if cell["route_id"] in ranked
    ]
    return {
        "routes": routes,
        "cells": cells,
        "ranking": routes[:RANKED_ROUTES],
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
    cells = [c for c in kpis.headway_route_hour(con, src, grp, day) if c["route_id"] in shown]
    figures = []
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
            ),
            _figure(
                "bunched",
                "Bunched",
                row["bunched_share"],
                pct(row["bunched_share"]),
                "At most 25 % of the scheduled headway.",
            ),
            _figure(
                "gaps",
                "Gaps",
                row["gap_share"],
                pct(row["gap_share"]),
                "At least twice the scheduled headway.",
            ),
            _figure(
                "irregular",
                "Irregular",
                irregular,
                pct(irregular),
                "Every other headway: off schedule, not extreme.",
            ),
        ]
    return {
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
    figures, outcomes = [], []
    if row is not None:
        figures = [
            _figure("scheduled", "Scheduled trips", row["scheduled"], count(row["scheduled"])),
            _figure(
                "not_delivered",
                "Not seen running",
                row["not_delivered_share"],
                pct(row["not_delivered_share"]),
                "Never reported + announced but never moved, as a share of the trips the feed "
                "could observe (trips that could not be judged excluded).",
                f"of {count(row['scheduled'] - row['unknown'])} observable trips",
            ),
            _figure(
                "unknown",
                "Could not be judged",
                row["unknown"],
                count(row["unknown"]),
                "Trips whose scheduled time fell outside the snapshots read or inside a feed "
                "outage.",
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
    caveat = _subway_caveat(con, src, day) if grp == "subway" else None
    return {
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
    return "—" if low is None or high is None else f"{int(low)}–{int(high)}"


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
    arrivals = sum(int(h["events"]) for h in hours)
    on_time_count = sum(int(h["on_time"]) for h in hours)
    share = on_time_count / arrivals if arrivals else None
    scored = sum(bool(h["sufficient"]) for h in hours)
    return {
        "hours": hours,
        "figures": [
            _figure("arrivals", "Arrivals observed", arrivals, count(arrivals)),
            _figure("on_time", "On time, all hours", share, pct(share)),
            _figure(
                "scored_hours",
                "Hours with enough data",
                scored,
                f"{scored} of {len(hours)}",
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


def stop_map(con: Con, src: Source, grp: str) -> Row:
    """BR8 map: located stops, least reliable sufficient stops first, then the thinly observed.

    A stop is sufficient with at least MIN_CELL_EVENTS arrivals pooled over all routes and hours
    (the same bar as one stop-hour on the stop reliability page).
    """
    stops = [
        {
            **s,
            "sufficient": s["events"] >= MIN_CELL_EVENTS,
            "label": f"{s['stop_name']} ({s['stop_id']})" if s["stop_name"] else s["stop_id"],
            "display": pct(s["on_time_share"]),
        }
        for s in kpis.stop_map(con, src, grp)
    ]
    ordered = sorted(stops, key=lambda s: (not s["sufficient"], s["on_time_share"], s["stop_id"]))
    worst = [s for s in ordered if s["sufficient"]][:MAP_WORST]
    return {
        "stops": ordered,
        "worst": worst,
        "sufficient": sum(s["sufficient"] for s in stops),
        "min_events": MIN_CELL_EVENTS,
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
    hours = [h for h in kpis.hourly_on_time(con, src, "bus") if h["events"] >= HOURLY_MIN_EVENTS]
    worst_hour = min(hours, key=lambda h: (h["on_time_share"], h["service_hour"]))
    best_hour = max(hours, key=lambda h: (h["on_time_share"], -h["service_hour"]))
    ranked = route_scorecards(con, src, "bus")["ranked"]
    last = ranked[-1]
    late = next(v for v in early_warning(con, src, "bus")["verdicts"] if v["outcome"] == "late")
    return [
        {
            "key": "modes",
            "kicker": "Bus vs subway",
            "value": pct(pooled["subway"][0]),
            "headline": (
                f"{pct(pooled['subway'][0])} of subway arrivals were on time, against "
                f"{pct(pooled['bus'][0])} of bus arrivals."
            ),
            "detail": (
                f"Both days pooled: {count(pooled['subway'][1])} subway and "
                f"{count(pooled['bus'][1])} bus inferred arrivals at intermediate stops."
            ),
            "page": "on-time",
        },
        {
            "key": "hours",
            "kicker": "Time of day",
            "value": pct(worst_hour["on_time_share"]),
            "headline": (
                f"Bus punctuality was lowest at {int(worst_hour['service_hour']):02d}:00 "
                f"({pct(worst_hour['on_time_share'])}) and highest at "
                f"{int(best_hour['service_hour']):02d}:00 ({pct(best_hour['on_time_share'])})."
            ),
            "detail": (
                f"Hours of the service day (scheduled time) with at least "
                f"{HOURLY_MIN_EVENTS:,} arrivals, both days pooled."
            ),
            "page": "on-time",
        },
        {
            "key": "route",
            "kicker": "Least punctual route",
            "value": pct(last["on_time_share"]),
            "headline": (
                f"Route {last['route_id']} ranked last of {len(ranked)} bus routes: "
                f"{pct(last['on_time_share'])} on time."
            ),
            "detail": (
                f"95 % interval {pct(last['ci_low'])} – {pct(last['ci_high'])}, "
                f"plausible ranks {last['rank_interval']}, from {count(last['events'])} arrivals."
            ),
            "page": "scorecards",
        },
        {
            "key": "warning",
            "kicker": "Early warning",
            "value": late.get("f1_display", "—"),
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
        "tests": f"{tests['passed']:,} / {tests['total']:,}" if tests["available"] else None,
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
    "(a late prediction at the earlier stop, 1–2 % of segments)."
)


def delay(con: Con, src: Source, grp: str, day: str) -> Row:
    """BR4: how much of a trip's final delay it inherited and how much it gained en route."""
    row = _pick(kpis.delay_overview(con, src), grp=grp, service_date=day)
    if row is None:
        return {"summary": None, "figures": [], "caption": None, "definitions": DELAY_DEFINITIONS}
    return {
        "summary": row,
        "figures": [
            _figure(
                "inherited",
                "Delay at first observed stop",
                row["mean_inherited_delay_s"],
                minutes(row["mean_inherited_delay_s"]),
                "Mean over trips (one row per trip and vehicle).",
            ),
            _figure(
                "gained",
                "Delay gained en route",
                row["mean_gained_delay_s"],
                minutes(row["mean_gained_delay_s"]),
                "Mean of the sum of segment excesses: observed minus scheduled travel time.",
            ),
            _figure(
                "final",
                "Delay at last observed stop",
                row["mean_final_delay_s"],
                minutes(row["mean_final_delay_s"]),
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
            "segment": (
                f"{int(r['service_hour']):02d}:00 · {r['route_id']} · "
                f"{r['from_name']} → {r['to_name']}"
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
        "definitions": WARNING_DEFINITIONS,
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
        feeds.append(
            {
                "feed": feed,
                "label": label,
                "score": row["score"],
                "display": score(row["score"]),
                "help": f"{row['passed']} of {row['checks']} checks passed",
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
