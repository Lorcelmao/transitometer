"""Shared app pieces: data connection, filters, chart helpers, provenance.

Labels, rules and display formatting live in transitometer.serve (views, format), shared with
the Next.js site.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

from transitometer.serve import evidence, kpis, snapshot
from transitometer.serve.format import day_label
from transitometer.serve.views import GROUPS, SHORT_GROUPS

BLUE = "#2563eb"  # single-series marks (the theme's primary colour)
MUTED = "#cbd5e1"  # outline of cells that are shown but not scored
# One hue, light -> dark; the lightest step stays clearly blue so it never reads as "no data".
SEQUENTIAL = ["#bfdbfe", "#60a5fa", "#2563eb", "#1e40af", "#172554"]
REPOSITORY_URL = "https://github.com/Lorcelmao/transitometer"


@st.cache_resource  # type: ignore[untyped-decorator]
def connection() -> tuple[Any, kpis.Source]:
    source = kpis.source_from_env()
    return kpis.connect(source), source


def manifest() -> dict[str, Any] | None:
    """The snapshot manifest when the app serves a snapshot, otherwise None."""
    _, src = connection()
    return snapshot.load_manifest(Path(src.root)) if src.kind == "snapshot" else None


def evidence_folder() -> Path:
    """The evidence files that belong to the data being shown."""
    _, src = connection()
    return evidence.folder_for(src.kind, src.root)


def snapshot_banner() -> None:
    """Shown on top of every page of a hosted snapshot: what this server does and does not run."""
    info = manifest()
    if info is None:
        return
    st.caption(
        f":material/inventory_2: Snapshot of the Spark pipeline's Gold output, validated on "
        f"{info['validated_on']} (commit `{info['validated_commit'][:7]}`). The streaming pipeline "
        f"(Kafka → Spark → Delta Lake) runs locally, not on this server; see the "
        f"[repository]({REPOSITORY_URL})."
    )


def frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


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
    info = manifest()
    if info is not None:
        origin = (
            f"a validated snapshot of the Spark pipeline's Gold tables (run recorded in commit "
            f"{info['validated_commit'][:7]} on {info['validated_on']})"
        )
    elif src.kind == "gold":
        origin = "the Spark pipeline's Gold tables (Delta Lake)"
    else:
        origin = "the frozen golden reference tables (DuckDB), which the Spark output matches"
    days = " and ".join(day_label(d) for d in kpis.service_dates(con, src))
    st.divider()
    st.caption(
        f"Data: real archived MTA GTFS-Realtime feeds (via the gtfsrt.io archive) for the service "
        f"days {days}, replayed through the pipeline — not a live feed. Values on this page come "
        f"from {origin}. Source data from the MTA, used under the MTA Terms of Use; this project "
        f"is not endorsed by the MTA."
    )
