"""Diagnostic pages: where delay builds up (BR4) and the early-warning rules (BR6).

Data, rules, labels and definitions come from transitometer.serve.views (shared with the Next.js
site); this module only lays them out.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from transitometer.app.common import (
    BLUE,
    connection,
    definitions,
    filters,
    frame,
    provenance_note,
)
from transitometer.serve import views


def page_delay_attribution() -> None:
    st.header("Where delay builds up")
    st.markdown(
        "Is a late trip late because it **started** late, or because it **lost time** along the "
        "way? Each trip's delay at its last observed stop splits exactly into the delay it "
        "already had at its first observed stop and the time it gained segment by segment."
    )
    con, src = connection()
    grp, day = filters("delay")
    view = views.delay(con, src, grp, day)
    if view["summary"] is None:
        st.warning("No trips were observed on this day.")
        provenance_note()
        return
    for column, figure in zip(st.columns(3), view["figures"], strict=True):
        column.metric(figure["label"], figure["display"], border=True, help=figure["help"])
    st.caption(view["caption"])

    st.subheader("Stop-to-stop segments that lose the most time (both days)")
    segments = views.costly_segments(con, src, grp)
    rows = frame(segments["segments"])
    if rows.empty:
        st.info("No segment was observed often enough to be ranked.")
    else:
        long = pd.concat(
            [
                rows.assign(measure="Scheduled", seconds=rows["sched_travel_s"]),
                rows.assign(measure="Typical (median)", seconds=rows["p50_travel_s"]),
            ]
        )
        chart = (
            alt.Chart(long, height=max(220, 34 * len(rows)))
            .mark_bar(cornerRadiusEnd=3, height={"band": 0.8})
            .encode(
                x=alt.X("seconds:Q", title="Travel time (s)"),
                y=alt.Y(
                    "segment:N",
                    sort=list(rows["segment"]),
                    title=None,
                    axis=alt.Axis(labelOverlap=False, labelLimit=420),
                ),
                yOffset=alt.YOffset("measure:N", sort=["Scheduled", "Typical (median)"]),
                color=alt.Color(
                    "measure:N",
                    title=None,
                    scale=alt.Scale(
                        domain=["Scheduled", "Typical (median)"], range=["#94a3b8", BLUE]
                    ),
                    legend=alt.Legend(orient="top"),
                ),
                tooltip=[
                    alt.Tooltip("segment", title="Segment"),
                    alt.Tooltip("segments", title="Observations"),
                    alt.Tooltip("sched_travel_s", title="Scheduled (s)"),
                    alt.Tooltip("p50_travel_s", title="Typical (s)"),
                    alt.Tooltip("p90_travel_s", title="Bad-day, p90 (s)"),
                    alt.Tooltip("median_excess_s", title="Typical excess (s)"),
                ],
            )
        )
        st.altair_chart(chart, width="stretch")
        st.caption(segments["caption"])
    definitions(view["definitions"])
    provenance_note()


def page_early_warning() -> None:
    st.header("Early warning")
    st.markdown(
        "Could an operator have seen trouble coming? Halfway through each trip, two simple "
        "rules predict whether it will **end late** or get **bunched** later. Each rule is "
        "compared with a naive baseline that only looks at the trip's current state."
    )
    con, src = connection()
    left, _ = st.columns([1, 3])
    with left:
        grp = (
            st.segmented_control(
                "Mode",
                list(views.GROUPS),
                format_func=views.SHORT_GROUPS.get,
                default="bus",
                key="warning-grp",
            )
            or "bus"
        )
    view = views.early_warning(con, src, grp)

    st.subheader(f"Held-out day ({view['held_out_label']}): did the rules pass?")
    for col, verdict in zip(st.columns(2), view["verdicts"], strict=True):
        if not verdict["available"]:
            col.info(f"{verdict['title']}: not measured.")
            continue
        with col, st.container(border=True):
            icon = ":material/check_circle:" if verdict["passed"] else ":material/cancel:"
            st.markdown(f"**{verdict['title']}** {icon} {verdict['verdict']}")
            st.markdown(
                f"F1 **{verdict['f1_display']}** vs baseline {verdict['baseline_f1_display']} · "
                f"precision **{verdict['precision_display']}** (target ≥ "
                f"{view['min_precision_display']}) · recall {verdict['recall_display']}"
            )
            st.caption(verdict["caption"])

    st.subheader("Rule vs baseline, both days")
    chart = (
        alt.Chart(frame(view["comparison"]), height=150)
        .mark_bar(cornerRadiusEnd=3, height={"band": 0.8})
        .encode(
            x=alt.X("f1:Q", title="F1 score (higher is better)", scale=alt.Scale(domain=[0, 1])),
            y=alt.Y("Method:N", title=None, sort=["Rule", "Baseline"]),
            color=alt.Color(
                "Method:N",
                scale=alt.Scale(domain=["Rule", "Baseline"], range=[BLUE, "#94a3b8"]),
                legend=None,
            ),
            row=alt.Row("outcome:N", title=None, header=alt.Header(labelFontWeight="bold")),
            column=alt.Column("day:N", title=None),
            tooltip=[
                "Method",
                alt.Tooltip("precision", format=".1%"),
                alt.Tooltip("recall", format=".1%"),
                alt.Tooltip("f1", format=".3f"),
                alt.Tooltip("decisions", format=","),
            ],
        )
    )
    st.altair_chart(chart)
    definitions(view["definitions"])
    provenance_note()
