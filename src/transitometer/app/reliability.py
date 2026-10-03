"""Reliability pages: on-time performance (BR1), headways (BR2), missing trips (BR3).

Data, rules, labels and definitions come from transitometer.serve.views (shared with the Next.js
site); this module only lays them out.
"""

from __future__ import annotations

from typing import Any

import altair as alt
import streamlit as st

from transitometer.app.common import (
    MUTED,
    SEQUENTIAL,
    connection,
    definitions,
    filters,
    frame,
    provenance_note,
    ranking_chart,
)
from transitometer.serve import views


def _metrics(figures: list[dict[str, Any]]) -> None:
    for column, figure in zip(st.columns(len(figures)), figures, strict=True):
        column.metric(figure["label"], figure["display"], help=figure["help"], border=True)


def page_otp() -> None:
    st.header("On-time performance")
    st.markdown(
        "How often did buses and trains reach their stops on schedule? An arrival is **on time** "
        "when it is at most **1 minute early** and at most **5 minutes late**."
    )
    con, src = connection()
    grp, day = filters("otp")
    view = views.on_time(con, src, grp, day)
    worst = frame(view["routes"])
    if worst.empty:
        st.warning("No route had enough observed arrivals on this day.")
        provenance_note()
        return
    cells = frame(view["cells"])
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
        f"Darker blue = more punctual. Outlined white cells had fewer than {view['min_events']} "
        "arrivals and are not scored. Hours past 23 belong to the same service day after "
        "midnight. Routes are ordered from least to most punctual."
    )
    st.altair_chart((thin + scored).properties(height=max(240, 26 * len(order))), width="stretch")

    st.subheader("Least punctual routes over the whole day")
    st.altair_chart(
        ranking_chart(
            frame(view["ranking"]),
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
    definitions(view["definitions"])
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
    view = views.headways(con, src, grp, day)
    if view["summary"] is None:
        st.warning("No headways were observed on this day.")
        provenance_note()
        return
    _metrics(view["figures"])

    bunched = frame(view["routes"])
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
    definitions(view["definitions"])
    provenance_note()


def page_missing_trips() -> None:
    st.header("Trip delivery")
    st.markdown(
        "Was every scheduled trip actually run? Each trip in the timetable gets exactly one "
        "outcome, from what the real-time feed reported."
    )
    con, src = connection()
    grp, day = filters("missing")
    view = views.missing_trips(con, src, grp, day)
    if view["summary"] is None:
        st.warning("No scheduled trips on this day.")
        provenance_note()
        return
    _metrics(view["figures"])
    outcomes = frame([{k: o[k] for k in ("outcome", "trips", "order")} for o in view["outcomes"]])
    not_delivered = " || ".join(
        f"datum.outcome == '{o['outcome']}'" for o in view["outcomes"] if o["not_delivered"]
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
            color=alt.condition(not_delivered, alt.value("#dc2626"), alt.value("#64748b"))
        )
        + bars.mark_text(align="left", dx=4, color="#1e293b").encode(
            text=alt.Text("trips:Q", format=",")
        ),
        width="stretch",
    )
    st.caption("Red bars are the trips counted as not seen running.")
    if view["caveat"] is not None:
        st.warning(view["caveat"]["text"], icon=":material/warning:")

    routes = frame(view["routes"])
    if not routes.empty:
        st.subheader("Routes with the most trips not seen running")
        st.altair_chart(
            ranking_chart(
                routes,
                "not_delivered_share",
                "Share of observable trips not seen running",
                [
                    alt.Tooltip("route_id", title="Route"),
                    alt.Tooltip("scheduled", title="Scheduled", format=","),
                    alt.Tooltip("missing", title="Never reported", format=","),
                    alt.Tooltip("not_run", title="Announced, never moved", format=","),
                    alt.Tooltip("unknown", title="Could not be judged", format=","),
                    alt.Tooltip("not_delivered_share", title="Not seen running", format=".1%"),
                ],
            ),
            width="stretch",
        )
    definitions(view["definitions"])
    provenance_note()
