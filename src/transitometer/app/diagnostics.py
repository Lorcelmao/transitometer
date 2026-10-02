"""Diagnostic pages: where delay builds up (BR4) and the early-warning rules (BR6)."""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from transitometer.app.common import (
    BLUE,
    GROUPS,
    connection,
    day_label,
    definitions,
    filters,
    frame,
    pct,
    provenance_note,
)
from transitometer.serve import kpis

MIN_SEGMENTS = 20  # segment-hours with fewer observations are not ranked
DEVELOPMENT_DAY, HELD_OUT_DAY = "20260922", "20260923"  # rules were tuned on the first day only
MIN_PRECISION = 0.6  # acceptance declared before the held-out day was computed


def _minutes(seconds: float | None) -> str:
    if seconds is None or pd.isna(seconds):
        return "—"
    sign = "−" if seconds < 0 else ""
    return f"{sign}{abs(seconds) / 60:.1f} min"


def page_delay_attribution() -> None:
    st.header("Where delay builds up")
    st.markdown(
        "Is a late trip late because it **started** late, or because it **lost time** along the "
        "way? Each trip's delay at its last observed stop splits exactly into the delay it "
        "already had at its first observed stop and the time it gained segment by segment."
    )
    con, src = connection()
    grp, day = filters("delay")
    row = next(
        (r for r in kpis.delay_overview(con, src) if r["grp"] == grp and r["service_date"] == day),
        None,
    )
    if row is None:
        st.warning("No trips were observed on this day.")
        provenance_note()
        return
    a, b, c = st.columns(3)
    a.metric(
        "Delay at first observed stop",
        _minutes(row["mean_inherited_delay_s"]),
        border=True,
        help="Mean over trips (one row per trip and vehicle).",
    )
    b.metric(
        "Delay gained en route",
        _minutes(row["mean_gained_delay_s"]),
        border=True,
        help="Mean of the sum of segment excesses: observed minus scheduled travel time.",
    )
    c.metric("Delay at last observed stop", _minutes(row["mean_final_delay_s"]), border=True)
    st.caption(
        f"{row['trip_vehicles']:,} trips. The split is exact for every one of them "
        f"({row['attribution_mismatches']} trips where inherited + gained ≠ final)."
    )

    st.subheader("Stop-to-stop segments that lose the most time (both days)")
    rows = frame(kpis.costly_segments(con, src, grp, MIN_SEGMENTS))
    if rows.empty:
        st.info("No segment was observed often enough to be ranked.")
    else:
        rows["segment"] = [
            f"{int(r.service_hour):02d}:00 · {r.route_id} · {r.from_name} → {r.to_name}"
            for r in rows.itertuples()
        ]
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
        st.caption(
            f"Pooled over both service days; segment-hours with at least {MIN_SEGMENTS} "
            "observations, ranked by their median excess over the timetable."
        )
    definitions(
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
    provenance_note()


def page_early_warning() -> None:
    st.header("Early warning")
    st.markdown(
        "Could an operator have seen trouble coming? Halfway through each trip, two simple "
        "rules predict whether it will **end late** or get **bunched** later. Each rule is "
        "compared with a naive baseline that only looks at the trip's current state."
    )
    con, src = connection()
    summary = frame(kpis.warning_summary(con, src))
    left, _ = st.columns([1, 3])
    with left:
        grp = (
            st.segmented_control(
                "Mode",
                list(GROUPS),
                format_func={"bus": "Bus", "subway": "Subway"}.get,
                default="bus",
                key="warning-grp",
            )
            or "bus"
        )

    held = summary[(summary["grp"] == grp) & (summary["service_date"] == HELD_OUT_DAY)]
    st.subheader(f"Held-out day ({day_label(HELD_OUT_DAY)}): did the rules pass?")
    cols = st.columns(2)
    for col, outcome, title in zip(
        cols, ["late", "bunched"], ["Ends late", "Gets bunched"], strict=True
    ):
        rule = held[(held["outcome"] == outcome) & (held["method"] == "rule")]
        base = held[(held["outcome"] == outcome) & (held["method"] == "baseline")]
        if rule.empty or base.empty:
            col.info(f"{title}: not measured.")
            continue
        r, b = rule.iloc[0], base.iloc[0]
        passed = r["f1"] > b["f1"] and r["precision"] >= MIN_PRECISION
        with col, st.container(border=True):
            icon = ":material/check_circle:" if passed else ":material/cancel:"
            st.markdown(f"**{title}** {icon} {'passed' if passed else 'did not pass'}")
            st.markdown(
                f"F1 **{r['f1']:.2f}** vs baseline {b['f1']:.2f} · precision "
                f"**{pct(r['precision'], 0)}** (target ≥ {pct(MIN_PRECISION, 0)}) · recall "
                f"{pct(r['recall'], 0)}"
            )
            st.caption(
                f"{int(r['decisions']):,} trips judged, {int(r['positives']):,} actually {outcome}."
            )

    st.subheader("Rule vs baseline, both days")
    view = summary[summary["grp"] == grp].copy()
    view["day"] = [
        f"{day_label(d)} ({'tuning' if d == DEVELOPMENT_DAY else 'held out'})"
        for d in view["service_date"]
    ]
    view["Method"] = view["method"].map({"rule": "Rule", "baseline": "Baseline"})
    chart = (
        alt.Chart(view, height=150)
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
    definitions(
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
    provenance_note()
