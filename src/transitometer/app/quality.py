"""Data-quality pages: feed health (BR7) and the pipeline's validation evidence."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from transitometer.app.common import (
    FEED_CHECKS,
    FEEDS,
    check_threshold,
    check_value,
    connection,
    day_label,
    definitions,
    frame,
    provenance_note,
)
from transitometer.serve import evidence, kpis

FEED_LABELS = {
    "trip_updates.bus": "Bus trip updates",
    "trip_updates.subway": "Subway trip updates",
    "vehicle_positions.bus": "Bus vehicle positions",
}


def page_feed_health() -> None:
    st.header("Feed health")
    st.markdown(
        "Every number in this app depends on the real-time feeds, so their quality is measured "
        "too. Each feed is checked every day against fixed thresholds: **8 checks** for a "
        "trip-update feed, **7** for the GPS feed. The **score** is the share of checks passed."
    )
    con, src = connection()
    scores = frame(kpis.feed_scores(con, src))
    days = list(scores["day"].unique())
    day = st.columns([1, 3])[0].selectbox("Day", days, format_func=day_label, key="feed-day")
    columns = st.columns(3)
    for column, feed in zip(columns, FEEDS, strict=True):
        row = scores[(scores["feed"] == feed) & (scores["day"] == day)]
        if row.empty:
            continue
        r = row.iloc[0]
        column.metric(
            FEEDS[feed],
            f"{r['score']:.1f} / 100",
            help=f"{r['passed']} of {r['checks']} checks passed",
            border=True,
        )
        failed = r["failed_checks"]
        if isinstance(failed, str) and failed:
            names = ", ".join(FEED_CHECKS.get(m, (m,))[0] for m in failed.split(", "))
            column.caption(f":material/error: Failed: {names}")
        else:
            column.caption(":material/check_circle: All checks passed")

    feed = (
        st.segmented_control(
            "Checks for", list(FEEDS), format_func=FEEDS.get, default="bus_tu", key="feed-pick"
        )
        or "bus_tu"
    )
    checks = frame(kpis.feed_checks(con, src, feed, day))
    table = pd.DataFrame(
        {
            "Result": checks["passed"].map({True: "Pass", False: "Fail"}),
            "Check": [FEED_CHECKS.get(m, (m,))[0] for m in checks["metric"]],
            "Measured": [
                check_value(m, v) for m, v in zip(checks["metric"], checks["value"], strict=True)
            ],
            "Threshold": [
                check_threshold(m, t)
                for m, t in zip(checks["metric"], checks["threshold"], strict=True)
            ],
            "What it measures": [FEED_CHECKS.get(m, ("", m))[1] for m in checks["metric"]],
        }
    )
    st.dataframe(table, hide_index=True, width="stretch")
    definitions(
        "- Lower is better for every check. A check with no data counts as **failed** rather "
        "than disappearing from the score.\n"
        "- Snapshot and GPS checks use the local calendar day of the snapshot; trip and stop "
        "checks use the service day.\n"
        "- *Missed polls* is measured on the archive's fetch times, not on the feed's own "
        "timestamps, which drift with the feed's publication lag.\n"
        "- p99 = 99th percentile."
    )
    provenance_note()


def _ratio(part: int, whole: int) -> str:
    return f"{part} / {whole}"


def _not_measured(what: str, files: str) -> None:
    st.info(f"{what}: not yet measured (no `{files}` in `results/`).", icon=":material/hourglass:")


def page_validation() -> None:
    st.header("Data & validation")
    st.markdown(
        "What the data is, and the evidence that the pipeline processed it correctly. Every "
        "figure on this page is read from a result file committed to the repository; nothing is "
        "typed in by hand. The evidence covers the full two-day run of the pipeline."
    )

    st.subheader("1 · Dataset provenance")
    st.dataframe(
        pd.DataFrame(
            [
                (
                    "MTA Bus trip updates",
                    "Predicted stop times per trip",
                    "gtfsrt.io archive (MTA feed)",
                ),
                (
                    "MTA Bus vehicle positions",
                    "GPS position of every bus",
                    "gtfsrt.io archive (MTA feed)",
                ),
                ("NYC Subway trip updates", "Lines 1–7 and S", "gtfsrt.io archive (MTA feed)"),
                ("MTA static timetables (GTFS)", "Scheduled trips and stop times", "MTA"),
            ],
            columns=["Dataset", "Content", "Source"],
        ),
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "The archive holds the feeds as the MTA published them. Here they are **replayed** through "
        "Kafka as protobuf messages, as a live feed would arrive; the pipeline does not connect to "
        "the live MTA feeds. Source data from the MTA, used under the MTA Terms of Use; not "
        "endorsed by the MTA."
    )

    st.subheader("2 · Source integrity")
    st.markdown("Did the data reach the lakehouse complete and unaltered?")
    integrity = evidence.source_integrity()
    if not integrity["available"]:
        _not_measured("Source integrity", ", ".join(integrity["files"]))
    else:
        feeds = integrity["feeds"]

        def yes(flag: bool) -> str:
            return "Yes" if flag else "No"

        checks: list[tuple[str, list[str]]] = [
            ("Snapshots replayed", [f"{f['snapshots']:,}" for f in feeds]),
            ("Archive rows", [f"{f['archive_rows']:,}" for f in feeds]),
            (
                "Kafka messages sent (incl. 1 marker per snapshot)",
                [f"{f['messages']:,}" for f in feeds],
            ),
            (
                "All acknowledged and read back",
                [yes(f["read_back_equal"] and f["all_acknowledged"]) for f in feeds],
            ),
            (
                "Sampled snapshots identical to the archive",
                [
                    _ratio(f["fidelity_sampled"] - f["fidelity_mismatched"], f["fidelity_sampled"])
                    for f in feeds
                ],
            ),
            ("Silver rows", [f"{f['silver_rows']:,}" for f in feeds]),
            ("Silver rows = archive rows", [yes(f["rows_equal"]) for f in feeds]),
            (
                "Duplicates / late / dead-lettered",
                [
                    " / ".join(str(f[k]) for k in ("duplicates", "late", "dead_lettered"))
                    for f in feeds
                ],
            ),
            ("Message counts balance", [yes(f["balanced"]) for f in feeds]),
        ]
        st.dataframe(
            pd.DataFrame(
                {"Check": [name for name, _ in checks]}
                | {
                    FEED_LABELS.get(f["feed"], f["feed"]): [values[i] for _, values in checks]
                    for i, f in enumerate(feeds)
                }
            ),
            hide_index=True,
            width="stretch",
        )
        days = ", ".join(integrity["days"])
        st.caption(
            f"Archive days read: {days} (UTC). Evidence: `results/replay-report.json`, "
            "`results/replay-verification.json`, `results/silver-ingest.json`."
        )

    st.subheader("3 · Golden-reference parity")
    st.markdown(
        "The same rules were implemented a second time, independently, as **DuckDB SQL** over the "
        "raw archive (the *golden reference*). Each Spark result table must equal its golden "
        "counterpart."
    )
    parity = evidence.golden_parity()
    if not parity["available"]:
        _not_measured("Golden-reference parity", "validation-silver.json / validation-gold.json")
    else:
        cols = st.columns(len(parity["layers"]))
        for col, layer in zip(cols, parity["layers"], strict=True):
            col.metric(
                f"{layer['layer'].title()} tables equal to golden",
                f"{layer['passed']} / {layer['total']}",
                border=True,
            )
        tables = pd.DataFrame(
            [
                {
                    "Layer": layer["layer"].title(),
                    "Table": t["table"],
                    "Result": "Equal" if t["ok"] else "Differs",
                    "Rows compared": t["rows"],
                }
                for layer in parity["layers"]
                for t in layer["tables"]
            ]
        )
        with st.expander("Every table", icon=":material/table:"):
            st.dataframe(
                tables,
                hide_index=True,
                width="stretch",
                column_config={"Rows compared": st.column_config.NumberColumn(format="localized")},
            )
        policy = json.loads(
            (evidence.REPO / "golden" / "tolerance.json").read_text(encoding="utf-8")
        )
        with st.expander("Tolerance policy", icon=":material/rule:"):
            st.markdown(policy["policy"])
        st.caption(
            "Parity shows that two independent implementations of the same written rules agree; "
            "it does not show that the rules themselves are the best possible definition. "
            "Evidence: `results/validation-silver.json`, `results/validation-gold.json`."
        )

    st.subheader("4 · Automated tests")
    tests = evidence.tests()
    if not tests["available"]:
        _not_measured("Recorded test results", tests["file"])
        st.caption(
            "The test suite runs on every push in continuous integration (`python tasks.py check`: "
            "lint, type check, unit and integration tests); its counts are not yet recorded in a "
            "result file."
        )
    else:
        st.json(tests)
    provenance_note()
