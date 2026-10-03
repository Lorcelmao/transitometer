"""Overview: what Transitometer measures, the day's scorecard, how it works, and why to trust it."""

from __future__ import annotations

from typing import Any

import streamlit as st

from transitometer.app.common import connection, evidence_folder, filters
from transitometer.app.common import provenance_note as _provenance
from transitometer.serve import views

LINKS: dict[str, Any] = {}  # page objects for in-text links, filled in by main


def _link(name: str, label: str) -> None:
    page = LINKS.get(name)
    if page is not None:
        st.page_link(page, label=label, icon=":material/arrow_forward:")


def _scorecard(grp: str, day: str) -> dict[str, Any]:
    con, src = connection()
    view = views.overview(con, src, grp, day)
    for column, figure in zip(st.columns(4), view["figures"], strict=True):
        column.metric(figure["label"], figure["display"], help=figure["help"], border=True)
    return view


def page() -> None:
    st.title("Transitometer")
    st.markdown(
        "#### Was the promised transit service actually delivered?\n"
        "Transitometer compares New York's **bus and subway timetables** with what the "
        "**real-time feeds** reported, to measure punctuality, bunching, missing trips and the "
        "quality of the feeds themselves."
    )
    st.info(
        "Built on **real archived data**: two service days of MTA feeds, replayed through a "
        "streaming pipeline. Not a live service and not an official MTA product.",
        icon=":material/history:",
    )

    st.subheader("The day at a glance")
    view = _scorecard(*filters("overview"))
    st.caption(
        f"{view['group_label']}, {view['day_label']}. Hover the help icons for each definition."
    )
    cols = st.columns(4)
    with cols[0]:
        _link("otp", "On-time performance")
    with cols[1]:
        _link("headways", "Headways and bunching")
    with cols[2]:
        _link("missing", "Missing trips")
    with cols[3]:
        _link("feed", "Feed health")

    st.subheader("How it works")
    steps = st.columns(4)
    steps[0].markdown(
        "**1 · Real data**  \nArchived MTA GTFS-Realtime snapshots (bus trip updates, bus GPS "
        "positions, subway trip updates) and the published timetables."
    )
    steps[1].markdown(
        "**2 · Streaming ingest**  \nEach snapshot is replayed as protobuf messages through "
        "**Kafka** and decoded by **Spark Structured Streaming** into **Delta Lake** "
        "(deduplicated, bad messages dead-lettered, counts reconciled)."
    )
    steps[2].markdown(
        "**3 · Analytics**  \n**Spark** batch jobs infer stop arrivals, match trips to the "
        "timetable and compute the reliability and feed-quality tables."
    )
    steps[3].markdown(
        "**4 · Serving**  \n**DuckDB** reads the Delta tables for this **Streamlit** app."
    )

    st.subheader("Why the numbers can be trusted")
    trust = views.trust(evidence_folder())
    integrity, parity = trust["integrity"], trust["parity"]
    left, right = st.columns(2)
    with left, st.container(border=True):
        if integrity["available"]:
            st.markdown(
                f"**Source integrity: {integrity['status']}**  \nIn the full two-day run, "
                f"{integrity['archive_rows_display']} archive rows reached the lakehouse "
                "unchanged: counts equal at every hop, sampled messages identical field by field."
            )
        else:
            st.markdown("**Source integrity:** not yet measured.")
    with right, st.container(border=True):
        if parity["available"]:
            st.markdown(
                f"**Golden-reference parity: {parity['display']} tables equal**  \nEvery Spark "
                f"result table was compared with an independent DuckDB implementation of the same "
                f"rules."
            )
        else:
            st.markdown("**Golden-reference parity:** not yet measured.")
    _link("validation", "See the evidence on Data & validation")
    _provenance()
