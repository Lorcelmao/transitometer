"""Scorecard pages: route reliability with uncertainty (BR5) and stop-level reliability (BR8)."""

from __future__ import annotations

import altair as alt
import streamlit as st

from transitometer.app.common import (
    BLUE,
    GROUPS,
    MUTED,
    SHORT_GROUPS,
    connection,
    definitions,
    frame,
    pct,
    provenance_note,
)
from transitometer.serve import kpis

SHOWN_ROUTES = 20
MIN_CELL_EVENTS = 10  # golden min_events: stop-hours with fewer arrivals are not scored
MIN_ROUTE_TRIPS = 5  # golden min_trips: routes with fewer trips are not ranked


def _mode(key: str) -> str:
    choice = st.segmented_control(
        "Mode", list(GROUPS), format_func=SHORT_GROUPS.get, default="bus", key=key
    )
    return choice or "bus"


def page_route_scorecards() -> None:
    st.header("Route scorecards")
    st.markdown(
        "Which routes are reliably on time, and how sure can we be? Each route's on-time share "
        "comes with a **95 % confidence interval**: a short interval means the estimate is "
        "solid, a long one means few observations. Both service days are pooled."
    )
    con, src = connection()
    grp = _mode("scorecard-grp")
    routes = frame(kpis.route_scorecards(con, src, grp))
    ranked = routes[routes["sufficient"]]
    if ranked.empty:
        st.warning("No route was observed often enough to be ranked.")
        provenance_note()
        return
    view = st.segmented_control(
        "Show",
        ["least", "most"],
        format_func={"least": "Least punctual", "most": "Most punctual"}.get,
        default="least",
        key="scorecard-view",
    )
    shown = ranked.tail(SHOWN_ROUTES) if view != "most" else ranked.head(SHOWN_ROUTES)
    shown = shown.sort_values("on_time_share", ascending=view != "most")
    order = list(shown["route_id"])
    base = alt.Chart(shown, height=max(200, 26 * len(shown))).encode(
        y=alt.Y("route_id:N", sort=order, title="Route", axis=alt.Axis(labelOverlap=False)),
        tooltip=[
            alt.Tooltip("route_id", title="Route"),
            alt.Tooltip("rank", title="Rank"),
            alt.Tooltip("on_time_share", title="On time", format=".1%"),
            alt.Tooltip("ci_low", title="95 % CI from", format=".1%"),
            alt.Tooltip("ci_high", title="95 % CI to", format=".1%"),
            alt.Tooltip("events", title="Arrivals", format=","),
            alt.Tooltip("trips", title="Trips", format=","),
        ],
    )
    interval = base.mark_rule(color=BLUE, strokeWidth=2).encode(
        x=alt.X(
            "ci_low:Q",
            title="Share of arrivals on time (dot) and 95 % interval (line)",
            axis=alt.Axis(format="%"),
        ),
        x2="ci_high:Q",
    )
    point = base.mark_point(filled=True, size=70, color=BLUE).encode(x="on_time_share:Q")
    st.altair_chart(interval + point, width="stretch")
    st.caption(
        f"Ranked among {len(ranked)} {GROUPS[grp]} routes with at least {MIN_ROUTE_TRIPS} trips "
        "and 10 arrivals. Where two routes' lines overlap, the data cannot tell them apart."
    )
    with st.expander("All ranked routes", icon=":material/table:"):
        table = ranked.assign(
            rank_interval=[
                f"{int(lo)}–{int(hi)}" if lo == lo and hi == hi else "—"
                for lo, hi in zip(ranked["rank_low"], ranked["rank_high"], strict=True)
            ]
        )
        st.dataframe(
            table[
                [
                    "rank",
                    "route_id",
                    "on_time_share",
                    "ci_low",
                    "ci_high",
                    "rank_interval",
                    "trips",
                    "events",
                ]
            ],
            hide_index=True,
            width="stretch",
            column_config={
                "rank": "Rank",
                "route_id": "Route",
                "on_time_share": st.column_config.NumberColumn("On time", format="percent"),
                "ci_low": st.column_config.NumberColumn("95 % CI from", format="percent"),
                "ci_high": st.column_config.NumberColumn("95 % CI to", format="percent"),
                "rank_interval": "Plausible ranks (95 %)",
                "trips": st.column_config.NumberColumn("Trips", format="localized"),
                "events": st.column_config.NumberColumn("Arrivals", format="localized"),
            },
        )
    definitions(
        "- **On-time share:** arrivals at intermediate stops within −1 / +5 min of the "
        "timetable, pooled over both service days (same definition as On-time performance).\n"
        "- **95 % interval:** a bootstrap that resamples whole **trips** 200 times (stops of one "
        "trip are not independent). The resampling weights come from a hash, so the result is "
        "exactly reproducible; the Spark result equals the independent DuckDB reference.\n"
        "- **Plausible ranks:** the rank a route gets in 95 % of the resamples.\n"
        f"- **Ranked:** routes with at least {MIN_ROUTE_TRIPS} trips and 10 arrivals; the others "
        "are left unranked rather than ranked on noise."
    )
    provenance_note()


def page_stop_reliability() -> None:
    st.header("Stop reliability")
    st.markdown(
        "For riders: how dependable is a route at **your stop**, hour by hour? Pick a route and "
        "a stop to see how often it arrived on time and how late it typically was."
    )
    con, src = connection()
    left, middle, right = st.columns([1, 1, 2])
    with left:
        grp = _mode("stop-grp")
    routes = kpis.stop_routes(con, src, grp)
    if not routes:
        st.warning("No stop was observed often enough on this mode.")
        provenance_note()
        return
    route = middle.selectbox("Route", routes, key=f"stop-route-{grp}")
    stops = frame(kpis.route_stops(con, src, grp, route))
    stops["label"] = [
        f"{name} ({stop_id})" if isinstance(name, str) and name else stop_id
        for name, stop_id in zip(stops["stop_name"], stops["stop_id"], strict=True)
    ]
    choice = right.selectbox(
        "Stop",
        list(range(len(stops))),
        format_func=lambda i: stops["label"].iloc[i],
        key=f"stop-pick-{grp}-{route}",
    )
    stop = stops.iloc[choice]
    direction = None if stop["direction_id"] != stop["direction_id"] else int(stop["direction_id"])
    hours = frame(kpis.stop_hours(con, src, grp, route, direction, stop["stop_id"]))
    scored = hours[hours["sufficient"]]
    arrivals, on_time = int(hours["events"].sum()), int(hours["on_time"].sum())
    a, b, c = st.columns(3)
    a.metric("Arrivals observed", f"{arrivals:,}", border=True)
    b.metric("On time, all hours", pct(on_time / arrivals if arrivals else None), border=True)
    c.metric(
        "Hours with enough data",
        f"{len(scored)} of {len(hours)}",
        help=f"Hours with at least {MIN_CELL_EVENTS} arrivals over both days.",
        border=True,
    )
    hours["Data"] = hours["sufficient"].map({True: "enough", False: f"under {MIN_CELL_EVENTS}"})
    base = alt.Chart(hours, height=260).encode(
        x=alt.X("service_hour:O", title="Hour of the service day (scheduled time)"),
        tooltip=[
            alt.Tooltip("service_hour", title="Hour"),
            alt.Tooltip("events", title="Arrivals"),
            alt.Tooltip("on_time_share", title="On time", format=".0%"),
            alt.Tooltip("ci_low", title="95 % CI from", format=".0%"),
            alt.Tooltip("ci_high", title="95 % CI to", format=".0%"),
            alt.Tooltip("p50_delay_s", title="Typical delay (s)"),
            alt.Tooltip("p90_delay_s", title="Bad-day delay, p90 (s)"),
        ],
    )
    color = alt.condition("datum.sufficient", alt.value(BLUE), alt.value(MUTED))
    interval = base.mark_rule(strokeWidth=2).encode(
        y=alt.Y(
            "ci_low:Q",
            title="Share of arrivals on time",
            axis=alt.Axis(format="%"),
            scale=alt.Scale(domain=[0, 1]),
        ),
        y2="ci_high:Q",
        color=color,
    )
    point = base.mark_point(filled=True, size=60).encode(y="on_time_share:Q", color=color)
    st.altair_chart(interval + point, width="stretch")
    st.caption(
        f"Dots: on-time share; lines: 95 % interval. Grey hours had fewer than {MIN_CELL_EVENTS} "
        "arrivals: shown for completeness, not scored."
    )
    with st.expander("Hour by hour", icon=":material/table:"):
        st.dataframe(
            hours[
                [
                    "service_hour",
                    "events",
                    "on_time_share",
                    "ci_low",
                    "ci_high",
                    "p50_delay_s",
                    "p90_delay_s",
                    "Data",
                ]
            ],
            hide_index=True,
            width="stretch",
            column_config={
                "service_hour": "Hour",
                "events": "Arrivals",
                "on_time_share": st.column_config.NumberColumn("On time", format="percent"),
                "ci_low": st.column_config.NumberColumn("95 % CI from", format="percent"),
                "ci_high": st.column_config.NumberColumn("95 % CI to", format="percent"),
                "p50_delay_s": "Typical delay (s)",
                "p90_delay_s": "Bad-day delay, p90 (s)",
            },
        )
    definitions(
        "- **Arrivals:** inferred arrivals of this route at this stop (see On-time performance), "
        "pooled over both service days.\n"
        "- **95 % interval:** the Wilson score interval. Arrivals in the same hour share "
        "traffic, so the interval is somewhat optimistic.\n"
        "- **Typical delay** is the median; **bad-day delay** is the 90th percentile "
        "(negative = early)."
    )
    provenance_note()
