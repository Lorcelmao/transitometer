"""Shared app pieces: data connection, labels, formatting, filters, charts, provenance."""

from __future__ import annotations

from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

from transitometer.serve import kpis

BLUE = "#2563eb"  # single-series marks (the theme's primary colour)
MUTED = "#cbd5e1"  # outline of cells that are shown but not scored
# One hue, light -> dark; the lightest step stays clearly blue so it never reads as "no data".
SEQUENTIAL = ["#bfdbfe", "#60a5fa", "#2563eb", "#1e40af", "#172554"]
GROUPS = {"bus": "MTA Bus", "subway": "NYC Subway (lines 1–7, S)"}
SHORT_GROUPS = {"bus": "Bus", "subway": "Subway"}  # labels for compact controls
FEEDS = {
    "bus_tu": "Bus trip updates",
    "subway_tu": "Subway trip updates",
    "bus_vp": "Bus vehicle positions",
}
MIN_EVENTS = kpis.MIN_EVENTS

# Feed-health checks: plain name, what it measures, and how its value is shown.
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


@st.cache_resource  # type: ignore[untyped-decorator]
def connection() -> tuple[Any, kpis.Source]:
    source = kpis.source_from_env()
    return kpis.connect(source), source


def frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def day_label(day: str) -> str:
    """'20260922' -> 'Tue 22 Sep 2026'."""
    stamp = pd.Timestamp(f"{day[:4]}-{day[4:6]}-{day[6:]}")
    return f"{stamp:%a} {stamp.day} {stamp:%b %Y}"


def pct(value: float | None, digits: int = 1) -> str:
    return "—" if value is None or pd.isna(value) else f"{100 * value:.{digits}f} %"


def check_value(metric: str, value: float | None) -> str:
    if value is None or pd.isna(value):
        return "no data"
    unit = FEED_CHECKS.get(metric, ("", "", ""))[2]
    return pct(value, 2) if unit == "%" else f"{value:,.1f} s"


def check_threshold(metric: str, threshold: float) -> str:
    unit = FEED_CHECKS.get(metric, ("", "", ""))[2]
    return f"≤ {pct(threshold, 2)}" if unit == "%" else f"≤ {threshold:,.0f} s"


def filters(key: str, modes: bool = True) -> tuple[str, str]:
    """Mode and service day in one row above the content."""
    con, src = connection()
    left, right, _ = st.columns([1, 1, 2])
    grp = "bus"
    if modes:
        grp = (
            left.segmented_control(
                "Mode", list(GROUPS), format_func=SHORT_GROUPS.get, default="bus", key=f"{key}-grp"
            )
            or "bus"
        )
    days = kpis.service_dates(con, src)
    day = right.selectbox("Service day", days, format_func=day_label, key=f"{key}-day")
    return grp, day


def ranking_chart(data: pd.DataFrame, value: str, title: str, tooltip: list[Any]) -> alt.Chart:
    """Horizontal bars, one series, in the given order; the tooltip carries the exact numbers."""
    height = max(160, 28 * len(data))
    return (
        alt.Chart(data, height=height)
        .mark_bar(color=BLUE, cornerRadiusEnd=4, height={"band": 0.7})
        .encode(
            x=alt.X(f"{value}:Q", title=title, axis=alt.Axis(format="%", grid=True)),
            y=alt.Y("route_id:N", sort=None, title="Route", axis=alt.Axis(labelOverlap=False)),
            tooltip=tooltip,
        )
    )


def definitions(text: str) -> None:
    """How the numbers on a page are defined, one click away."""
    with st.expander("How these numbers are defined", icon=":material/info:"):
        st.markdown(text)


def provenance_note() -> None:
    """Shown at the foot of every page: what the data is and where it was computed."""
    con, src = connection()
    origin = (
        "the Spark pipeline's Gold tables (Delta Lake)"
        if src.kind == "gold"
        else "the frozen golden reference tables (DuckDB), which the Spark output matches"
    )
    days = " and ".join(day_label(d) for d in kpis.service_dates(con, src))
    st.divider()
    st.caption(
        f"Data: real archived MTA GTFS-Realtime feeds (via the gtfsrt.io archive) for the service "
        f"days {days}, replayed through the pipeline — not a live feed. Values on this page come "
        f"from {origin}. Source data from the MTA, used under the MTA Terms of Use; this project "
        f"is not endorsed by the MTA."
    )
