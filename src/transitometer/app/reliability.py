"""Reliability pages: on-time performance (BR1), headways (BR2), missing trips (BR3)."""

from __future__ import annotations

from typing import Any

import altair as alt
import streamlit as st

from transitometer.app.common import (
    MIN_EVENTS,
    MUTED,
    SEQUENTIAL,
    connection,
    definitions,
    filters,
    frame,
    pct,
    provenance_note,
    ranking_chart,
)
from transitometer.serve import kpis

HEATMAP_ROUTES = 25


def _pick(rows: list[dict[str, Any]], grp: str, day: str) -> dict[str, Any] | None:
    return next((r for r in rows if r["grp"] == grp and r["service_date"] == day), None)


def page_otp() -> None:
    st.header("On-time performance")
    st.markdown(
        "How often did buses and trains reach their stops on schedule? An arrival is **on time** "
        "when it is at most **1 minute early** and at most **5 minutes late**."
    )
    con, src = connection()
    grp, day = filters("otp")
    worst = frame(kpis.least_punctual_routes(con, src, grp, day, limit=HEATMAP_ROUTES))
    if worst.empty:
        st.warning("No route had enough observed arrivals on this day.")
        provenance_note()
        return
    cells = frame(kpis.otp_route_hour(con, src, grp, day))
    cells = cells[cells["route_id"].isin(worst["route_id"])].copy()
    cells["scored"] = cells["events"] >= MIN_EVENTS
    order = list(worst["route_id"])
    base = alt.Chart(cells).encode(
        x=alt.X("service_hour:O", title="Hour of the service day (scheduled time)"),
        y=alt.Y("route_id:N", sort=order, title="Route", axis=alt.Axis(labelOverlap=False)),
        tooltip=[
            alt.Tooltip("route_id", title="Route"),
            alt.Tooltip("service_hour", title="Hour"),
            alt.Tooltip("events", title="Arrivals", format=","),
            alt.Tooltip("on_time_share", title="On time", format=".1%"),
            alt.Tooltip("late_share", title="Late", format=".1%"),
            alt.Tooltip("median_delay_s", title="Median delay (s)"),
        ],
    )
    scored = (
        base.transform_filter("datum.scored")
        .mark_rect(stroke="white", strokeWidth=1.5)
        .encode(
            color=alt.Color(
                "on_time_share:Q",
                title="On time",
                scale=alt.Scale(domain=[0, 1], range=SEQUENTIAL),
                legend=alt.Legend(format="%"),
            )
        )
    )
    thin = base.transform_filter("!datum.scored").mark_rect(
        fill="white", stroke=MUTED, strokeWidth=1
    )
    st.subheader(f"The {len(order)} least punctual routes, hour by hour")
    st.caption(
        f"Darker blue = more punctual. Outlined white cells had fewer than {MIN_EVENTS} arrivals "
        "and are not scored. Hours past 23 belong to the same service day after midnight. Routes "
        "are ordered from least to most punctual."
    )
    st.altair_chart((thin + scored).properties(height=max(240, 26 * len(order))), width="stretch")

    st.subheader("Least punctual routes over the whole day")
    shown = worst.head(15)
    st.altair_chart(
        ranking_chart(
            shown,
            "on_time_share",
            "Share of arrivals on time",
            [
                alt.Tooltip("route_id", title="Route"),
                alt.Tooltip("events", title="Arrivals", format=","),
                alt.Tooltip("on_time_share", title="On time", format=".1%"),
                alt.Tooltip("late_share", title="Late", format=".1%"),
            ],
        ),
        width="stretch",
    )
    with st.expander("Table", icon=":material/table:"):
        st.dataframe(
            worst,
            hide_index=True,
            width="stretch",
            column_config={
                "route_id": "Route",
                "events": st.column_config.NumberColumn("Arrivals", format="localized"),
                "on_time_share": st.column_config.NumberColumn("On time", format="percent"),
                "late_share": st.column_config.NumberColumn("Late", format="percent"),
            },
        )
    definitions(
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
    provenance_note()


def page_headways() -> None:
    st.header("Headways and bunching")
    st.markdown(
        "Riders feel reliability as waiting time. A **headway** is the time between two "
        "consecutive vehicles of a route at a stop. Vehicles **bunch** when one catches up with "
        "the one ahead, leaving a long **gap** behind them."
    )
    con, src = connection()
    grp, day = filters("headways")
    row = _pick(kpis.headway_overview(con, src), grp, day)
    if row is None:
        st.warning("No headways were observed on this day.")
        provenance_note()
        return
    irregular = max(0.0, 1 - row["regular_share"] - row["bunched_share"] - row["gap_share"])
    a, b, c, d, e = st.columns(5)
    a.metric("Headways observed", f"{row['headways']:,}", border=True)
    b.metric(
        "Regular",
        pct(row["regular_share"]),
        help="Within ±20 % of the scheduled headway.",
        border=True,
    )
    c.metric(
        "Bunched",
        pct(row["bunched_share"]),
        help="At most 25 % of the scheduled headway.",
        border=True,
    )
    d.metric(
        "Gaps", pct(row["gap_share"]), help="At least twice the scheduled headway.", border=True
    )
    e.metric(
        "Irregular",
        pct(irregular),
        help="Every other headway: off schedule, not extreme.",
        border=True,
    )

    bunched = frame(kpis.most_bunched_routes(con, src, grp, day))
    if not bunched.empty:
        st.subheader("Routes with the most bunching")
        st.altair_chart(
            ranking_chart(
                bunched,
                "bunched_share",
                "Share of headways bunched",
                [
                    alt.Tooltip("route_id", title="Route"),
                    alt.Tooltip("headways", title="Headways", format=","),
                    alt.Tooltip("bunched_share", title="Bunched", format=".1%"),
                    alt.Tooltip("gaps", title="Gaps", format=","),
                    alt.Tooltip("regular_share", title="Regular", format=".1%"),
                ],
            ),
            width="stretch",
        )
        with st.expander("Table", icon=":material/table:"):
            st.dataframe(
                bunched,
                hide_index=True,
                width="stretch",
                column_config={
                    "route_id": "Route",
                    "headways": st.column_config.NumberColumn("Headways", format="localized"),
                    "bunched": st.column_config.NumberColumn("Bunched", format="localized"),
                    "gaps": st.column_config.NumberColumn("Gaps", format="localized"),
                    "bunched_share": st.column_config.NumberColumn(
                        "Bunched share", format="percent"
                    ),
                    "regular_share": st.column_config.NumberColumn(
                        "Regular share", format="percent"
                    ),
                },
            )
    definitions(
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
    provenance_note()


def page_missing_trips() -> None:
    st.header("Missing trips")
    st.markdown(
        "Was every scheduled trip actually run? Each trip in the timetable gets exactly one "
        "outcome, from what the real-time feed reported."
    )
    con, src = connection()
    grp, day = filters("missing")
    row = _pick(kpis.delivery_overview(con, src), grp, day)
    if row is None:
        st.warning("No scheduled trips on this day.")
        provenance_note()
        return
    a, b, c = st.columns(3)
    a.metric("Scheduled trips", f"{row['scheduled']:,}", border=True)
    b.metric(
        "Not delivered",
        pct(row["not_delivered_share"]),
        help="Missing + not run, as a share of the trips the feed could observe "
        "(unknown excluded).",
        border=True,
    )
    c.metric(
        "Could not be judged",
        f"{row['unknown']:,}",
        help="Trips whose scheduled time fell outside the snapshots read or inside a feed outage.",
        border=True,
    )
    outcomes = frame(
        [
            {"outcome": label, "trips": int(row[key]), "order": i}
            for i, (key, label) in enumerate(
                [
                    ("delivered", "Delivered"),
                    ("partial", "Partial"),
                    ("not_run", "Not run"),
                    ("missing", "Missing"),
                    ("unknown", "Unknown"),
                ]
            )
        ]
    )
    bars = alt.Chart(outcomes, height=200).encode(
        x=alt.X("trips:Q", title="Scheduled trips", scale=alt.Scale(nice=True)),
        y=alt.Y(
            "outcome:N",
            sort=alt.EncodingSortField("order"),
            title=None,
            axis=alt.Axis(labelOverlap=False),
        ),
        tooltip=[alt.Tooltip("outcome", title="Outcome"), alt.Tooltip("trips", format=",")],
    )
    st.altair_chart(
        bars.mark_bar(cornerRadiusEnd=4, height={"band": 0.7}).encode(
            color=alt.condition(
                "datum.outcome == 'Missing' || datum.outcome == 'Not run'",
                alt.value("#dc2626"),
                alt.value("#64748b"),
            )
        )
        + bars.mark_text(align="left", dx=4, color="#1e293b").encode(
            text=alt.Text("trips:Q", format=",")
        ),
        width="stretch",
    )
    st.caption("Red bars are the trips counted as not delivered.")
    if grp == "subway":
        unmatched = kpis.feed_metric(con, src, "subway_tu", day, "unknown_trip_share")
        st.warning(
            f"**Read subway 'missing' with care.** {pct(unmatched)} of the subway's real-time "
            "trips on this day could not be matched to a scheduled trip (their IDs differ from "
            "the timetable). Some scheduled trips counted as missing probably ran under such an "
            "ID.",
            icon=":material/warning:",
        )

    routes = frame(kpis.least_delivered_routes(con, src, grp, day))
    if not routes.empty:
        st.subheader("Routes with the most undelivered trips")
        st.altair_chart(
            ranking_chart(
                routes,
                "not_delivered_share",
                "Share of observable trips not delivered",
                [
                    alt.Tooltip("route_id", title="Route"),
                    alt.Tooltip("scheduled", title="Scheduled", format=","),
                    alt.Tooltip("missing", title="Missing", format=","),
                    alt.Tooltip("not_run", title="Not run", format=","),
                    alt.Tooltip("unknown", title="Unknown", format=","),
                    alt.Tooltip("not_delivered_share", title="Not delivered", format=".1%"),
                ],
            ),
            width="stretch",
        )
    definitions(
        "Each scheduled trip on a route the feed carries that day gets the **first** outcome "
        "that applies:\n"
        "1. **Delivered:** reported, and at least half of its intermediate stops observed as "
        "passed.\n"
        "2. **Unknown:** not delivered, and the feed could not tell: the trip's scheduled time "
        "falls outside the snapshots read or overlaps a feed outage longer than 5 minutes.\n"
        "3. **Missing:** never reported in the feed under any matching rule.\n"
        "4. **Not run:** reported, but no stop was ever passed and (for buses) no GPS arrival at "
        "the last stop.\n"
        "5. **Partial:** seen running, but fewer than half of its stops observed as passed.\n\n"
        "**Not delivered** = (missing + not run) ÷ (scheduled − unknown). Route ranking: routes "
        f"with at least {kpis.MIN_TRIPS} observable trips."
    )
    provenance_note()
