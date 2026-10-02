"""Overview: what Transitometer measures, the day's scorecard, how it works, and why to trust it."""

from __future__ import annotations

from typing import Any

import streamlit as st

from transitometer.app.common import GROUPS, connection, day_label, filters, pct
from transitometer.app.common import provenance_note as _provenance
from transitometer.serve import evidence, kpis

LINKS: dict[str, Any] = {}  # page objects for in-text links, filled in by main


def _link(name: str, label: str) -> None:
    page = LINKS.get(name)
    if page is not None:
        st.page_link(page, label=label, icon=":material/arrow_forward:")


def _scorecard(grp: str, day: str) -> None:
    con, src = connection()

    def pick(rows: list[dict[str, Any]], **match: str) -> dict[str, Any] | None:
        return next((r for r in rows if all(r.get(k) == v for k, v in match.items())), None)

    otp = pick(kpis.otp_overview(con, src), grp=grp, service_date=day, scope="all_stops")
    heads = pick(kpis.headway_overview(con, src), grp=grp, service_date=day)
    trips = pick(kpis.delivery_overview(con, src), grp=grp, service_date=day)
    feed = pick(kpis.feed_scores(con, src), feed=f"{grp}_tu", day=day)
    a, b, c, d = st.columns(4)
    a.metric(
        "Arrivals on time",
        pct(otp["on_time_share"]) if otp else "—",
        help="Share of inferred arrivals at intermediate scheduled stops that were at most 1 min "
        "early and at most 5 min late (the MTA's on-time band).",
        border=True,
    )
    b.metric(
        "Headways bunched",
        pct(heads["bunched_share"]) if heads else "—",
        help="Share of observed gaps between consecutive vehicles that were at most a quarter of "
        "the scheduled gap: vehicles arriving in clumps.",
        border=True,
    )
    c.metric(
        "Scheduled trips not delivered",
        pct(trips["not_delivered_share"]) if trips else "—",
        help="Missing (never reported) plus not run (announced, never seen moving), as a share "
        "of the scheduled trips the feed could observe.",
        border=True,
    )
    d.metric(
        "Feed quality score",
        f"{feed['score']:.1f} / 100" if feed else "—",
        help="Share of the feed's data-quality checks that passed (trip-update feed of this "
        "mode, this day).",
        border=True,
    )


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
    grp, day = filters("overview")
    _scorecard(grp, day)
    st.caption(f"{GROUPS[grp]}, {day_label(day)}. Hover the help icons for each definition.")
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
    integrity, parity = evidence.source_integrity(), evidence.golden_parity()
    left, right = st.columns(2)
    with left, st.container(border=True):
        if integrity["available"]:
            rows = sum(f["archive_rows"] for f in integrity["feeds"])
            status = "checks passed" if integrity["ok"] else "a check failed"
            st.markdown(
                f"**Source integrity: {status}**  \nIn the full two-day run, {rows:,} archive rows "
                "reached the lakehouse unchanged: counts equal at every hop, sampled messages "
                "identical field by field."
            )
        else:
            st.markdown("**Source integrity:** not yet measured.")
    with right, st.container(border=True):
        if parity["available"]:
            passed = sum(layer["passed"] for layer in parity["layers"])
            total = sum(layer["total"] for layer in parity["layers"])
            st.markdown(
                f"**Golden-reference parity: {passed} / {total} tables equal**  \nEvery Spark "
                f"result table was compared with an independent DuckDB implementation of the same "
                f"rules."
            )
        else:
            st.markdown("**Golden-reference parity:** not yet measured.")
    _link("validation", "See the evidence on Data & validation")
    _provenance()
