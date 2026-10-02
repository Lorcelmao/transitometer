"""Transitometer app: was the promised transit service actually delivered?

Pages read the KPI tables through transitometer.serve.kpis, either from the Spark Gold layer
(TRANSITOMETER_APP_SOURCE=gold) or from the frozen golden reference (=golden, the default).

Run: streamlit run src/transitometer/app/main.py
"""

from __future__ import annotations

from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

from transitometer.serve import kpis

BLUE = "#2a78d6"  # single-series marks
SEQUENTIAL = ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"]  # one hue, light -> dark
HEATMAP_ROUTES = 25
GROUPS = {"bus": "MTA Bus", "subway": "NYC Subway (1-7, S)"}
FEEDS = {
    "bus_tu": "Bus trip updates",
    "subway_tu": "Subway trip updates",
    "bus_vp": "Bus vehicle positions",
}

st.set_page_config(page_title="Transitometer", layout="wide")


@st.cache_resource  # type: ignore[untyped-decorator]
def _connection() -> tuple[Any, kpis.Source]:
    source = kpis.source_from_env()
    return kpis.connect(source), source


CON, SRC = _connection()


def frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def day_label(day: str) -> str:
    return f"{day[:4]}-{day[4:6]}-{day[6:]}"


def pct(value: float) -> str:
    return f"{100 * value:.1f} %"


def filters(key: str) -> tuple[str, str]:
    """Mode and service day, side by side above the charts."""
    left, right, _ = st.columns([1, 1, 2])
    grp = left.selectbox("Mode", list(GROUPS), format_func=GROUPS.get, key=f"{key}-grp")
    days = kpis.service_dates(CON, SRC)
    day = right.selectbox("Service day", days, format_func=day_label, key=f"{key}-day")
    return grp, day


def ranking_chart(data: pd.DataFrame, value: str, title: str) -> alt.Chart:
    """Horizontal bars, one series, sorted as given; tooltip carries the exact numbers."""
    return (
        alt.Chart(data)
        .mark_bar(color=BLUE, cornerRadiusEnd=4, height={"band": 0.7})
        .encode(
            x=alt.X(f"{value}:Q", title=title, axis=alt.Axis(format="%", grid=True)),
            y=alt.Y("route_id:N", sort=None, title="Route"),
            tooltip=[alt.Tooltip(c, format=".1%") if "share" in c else c for c in data.columns],
        )
    )


def page_overview() -> None:
    st.title("Transitometer")
    st.markdown(
        "Measures whether New York's promised bus and subway service was actually delivered, "
        "from real archived GTFS-Realtime feeds for **22–23 September 2026**."
    )
    st.markdown(
        "**Pipeline:** archived GTFS-RT → protobuf replay into **Kafka** → **Spark Structured "
        "Streaming** (Silver: decode, dedup, dead-letter, stop events) → **Delta Lake** (Gold "
        "KPIs) → **DuckDB** → this app. An independent **DuckDB** batch pipeline over the raw "
        "archive is the golden reference every Gold table is checked against."
    )
    label = "Spark Gold (Delta)" if SRC.kind == "gold" else "Golden reference (frozen Parquet)"
    st.info(f"Data source: **{label}**")
    otp = frame(kpis.otp_overview(CON, SRC))
    otp = otp[otp["scope"] == "all_stops"]
    columns = st.columns(len(otp))
    for column, row in zip(columns, otp.itertuples(), strict=True):
        column.metric(
            f"{GROUPS[row.grp]} · {day_label(row.service_date)}",
            pct(row.on_time_share),
            help=f"Share of {row.events:,} observed stop arrivals within −1/+5 min of schedule",
        )
    st.caption("On-time share: observed stop arrivals within −1 / +5 minutes of the timetable.")


def page_otp() -> None:
    st.header("On-time performance")
    st.caption("BR1 · arrivals within −1 / +5 min of schedule, per route and service hour.")
    grp, day = filters("otp")
    worst = frame(kpis.least_punctual_routes(CON, SRC, grp, day, limit=HEATMAP_ROUTES))
    if worst.empty:
        st.warning("No routes with enough observed arrivals for this selection.")
        return
    cells = frame(kpis.otp_route_hour(CON, SRC, grp, day))
    cells = cells[cells["route_id"].isin(worst["route_id"])]
    order = list(worst["route_id"])
    heatmap = (
        alt.Chart(cells)
        .mark_rect(stroke="white", strokeWidth=2)
        .encode(
            x=alt.X("service_hour:O", title="Service hour"),
            y=alt.Y("route_id:N", sort=order, title="Route"),
            color=alt.Color(
                "on_time_share:Q",
                title="On-time share",
                scale=alt.Scale(domain=[0, 1], range=SEQUENTIAL),
                legend=alt.Legend(format="%"),
            ),
            tooltip=[
                "route_id",
                "service_hour",
                "events",
                alt.Tooltip("on_time_share", format=".1%"),
                alt.Tooltip("late_share", format=".1%"),
                alt.Tooltip("median_delay_s", title="median delay (s)"),
            ],
        )
    )
    st.subheader(f"{HEATMAP_ROUTES} least punctual routes, by hour")
    st.altair_chart(heatmap, width="stretch")
    st.subheader("Least punctual routes")
    st.altair_chart(
        ranking_chart(worst.head(15), "on_time_share", "On-time share"), width="stretch"
    )
    with st.expander("Table"):
        st.dataframe(worst, hide_index=True, width="stretch")


def page_headways() -> None:
    st.header("Headways and bunching")
    st.caption(
        "BR2 · observed gaps between consecutive vehicles at a stop, compared with the scheduled "
        "headway: bunched when more than 20 % shorter, a gap when more than 20 % longer."
    )
    grp, day = filters("headways")
    summary = frame(kpis.headway_overview(CON, SRC))
    row = summary[(summary["grp"] == grp) & (summary["service_date"] == day)].iloc[0]
    a, b, c, d = st.columns(4)
    a.metric("Headways observed", f"{row['headways']:,}")
    b.metric("Regular", pct(row["regular_share"]))
    c.metric("Bunched", pct(row["bunched_share"]))
    d.metric("Gaps", pct(row["gap_share"]))
    bunched = frame(kpis.most_bunched_routes(CON, SRC, grp, day))
    if bunched.empty:
        st.warning("No routes with enough observed headways for this selection.")
        return
    st.subheader("Most bunched routes")
    st.altair_chart(
        ranking_chart(bunched, "bunched_share", "Share of headways bunched"),
        width="stretch",
    )
    with st.expander("Table"):
        st.dataframe(bunched, hide_index=True, width="stretch")


def page_missing_trips() -> None:
    st.header("Missing trips")
    st.caption(
        "BR3 · every scheduled trip, classified: delivered, partial, missing (never reported), "
        "not run (announced but never seen moving) or unknown (the feed could not tell)."
    )
    grp, day = filters("missing")
    summary = frame(kpis.delivery_overview(CON, SRC))
    row = summary[(summary["grp"] == grp) & (summary["service_date"] == day)].iloc[0]
    a, b, c, d = st.columns(4)
    a.metric("Scheduled trips", f"{row['scheduled']:,}")
    b.metric("Delivered", f"{row['delivered']:,}")
    c.metric("Missing", f"{row['missing']:,}")
    d.metric("Not delivered", pct(row["not_delivered_share"]), help="missing + not run")
    routes = frame(kpis.least_delivered_routes(CON, SRC, grp, day))
    if routes.empty:
        st.warning("No routes with enough observable trips for this selection.")
        return
    st.subheader("Routes with the most undelivered trips")
    st.altair_chart(
        ranking_chart(routes, "not_delivered_share", "Share of trips not delivered"),
        width="stretch",
    )
    with st.expander("Table"):
        st.dataframe(routes, hide_index=True, width="stretch")


def page_feed_health() -> None:
    st.header("Feed health")
    st.caption(
        "BR7 · data-quality checks on each real-time feed and day: staleness, missed polls, "
        "position jumps, ambiguous or unmatched trips. Score = share of checks passed."
    )
    scores = frame(kpis.feed_scores(CON, SRC))
    columns = st.columns(3)
    for index, row in enumerate(scores.itertuples()):
        columns[index % 3].metric(
            f"{FEEDS.get(row.feed, row.feed)} · {day_label(row.day)}",
            f"{row.score:.1f} / 100",
            help=f"{row.passed} of {row.checks} checks passed",
        )
    left, right, _ = st.columns([1, 1, 2])
    feed = left.selectbox("Feed", list(scores["feed"].unique()), format_func=FEEDS.get)
    day = right.selectbox("Day", list(scores["day"].unique()), format_func=day_label)
    checks = frame(kpis.feed_checks(CON, SRC, feed, day))
    checks.insert(0, "status", checks.pop("passed").map({True: "✅ pass", False: "❌ fail"}))
    st.dataframe(checks, hide_index=True, width="stretch")


PAGES = {
    "Overview": page_overview,
    "On-time performance": page_otp,
    "Headways and bunching": page_headways,
    "Missing trips": page_missing_trips,
    "Feed health": page_feed_health,
}
choice = st.sidebar.radio("Page", list(PAGES))
PAGES[choice]()
