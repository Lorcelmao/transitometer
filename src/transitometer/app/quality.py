"""Data-quality pages: feed health (BR7) and the pipeline's validation evidence."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from transitometer.app.common import (
    connection,
    definitions,
    evidence_folder,
    frame,
    provenance_note,
)
from transitometer.serve import evidence, views
from transitometer.serve.format import day_label


def page_feed_health() -> None:
    st.header("Feed health")
    st.markdown(
        "Every number in this app depends on the real-time feeds, so their quality is measured "
        "too. Each feed is checked every day against fixed thresholds: **8 checks** for a "
        "trip-update feed, **7** for the GPS feed. The **score** is the share of checks passed."
    )
    con, src = connection()
    days = views.feed_days(con, src)
    day = st.columns([1, 3])[0].selectbox("Day", days, format_func=day_label, key="feed-day")
    view = views.feed_health(con, src, day)
    feeds = {f["feed"]: f for f in view["feeds"]}
    for column, feed in zip(st.columns(3), views.FEEDS, strict=True):
        if feed not in feeds:
            continue
        info = feeds[feed]
        column.metric(info["label"], info["display"], help=info["help"], border=True)
        if info["failed"]:
            column.caption(f":material/error: Failed: {', '.join(info['failed'])}")
        else:
            column.caption(":material/check_circle: All checks passed")

    feed = (
        st.segmented_control(
            "Checks for",
            list(views.FEEDS),
            format_func=views.FEEDS.get,
            default="bus_tu",
            key="feed-pick",
        )
        or "bus_tu"
    )
    checks = feeds[feed]["checks"] if feed in feeds else []
    table = pd.DataFrame(
        {
            "Result": [c["result"] for c in checks],
            "Check": [c["check"] for c in checks],
            "Measured": [c["measured"] for c in checks],
            "Threshold": [c["threshold_display"] for c in checks],
            "What it measures": [c["description"] for c in checks],
        }
    )
    st.dataframe(table, hide_index=True, width="stretch")
    definitions(view["definitions"])
    provenance_note()


def _shown(folder: Path) -> str:
    """An evidence folder as shown to readers: repository-relative when inside the repository."""
    try:
        return f"{folder.relative_to(evidence.REPO).as_posix()}/"
    except ValueError:
        return f"{folder.as_posix()}/"


def _not_measured(what: str, files: str, folder: str) -> None:
    st.info(f"{what}: not yet measured (no `{files}` in `{folder}`).", icon=":material/hourglass:")


def page_validation() -> None:
    st.header("Data & validation")
    st.markdown(
        "What the data is, and the evidence that the pipeline processed it correctly. Every "
        "figure on this page is read from a result file committed to the repository; nothing is "
        "typed in by hand. The evidence covers the full two-day run of the pipeline."
    )

    folder = evidence_folder()
    view = views.validation(folder)
    st.subheader("1 · Dataset provenance")
    st.dataframe(frame(view["datasets"]), hide_index=True, width="stretch")
    st.caption(
        "The archive holds the feeds as the MTA published them. Here they are **replayed** through "
        "Kafka as protobuf messages, as a live feed would arrive; the pipeline does not connect to "
        "the live MTA feeds. Source data from the MTA, used under the MTA Terms of Use; not "
        "endorsed by the MTA."
    )

    where = _shown(folder)
    st.subheader("2 · Source integrity")
    st.markdown("Did the data reach the lakehouse complete and unaltered?")
    integrity = view["integrity"]
    if not integrity["available"]:
        _not_measured("Source integrity", ", ".join(integrity["files"]), where)
    else:
        st.dataframe(frame(view["integrity_table"]), hide_index=True, width="stretch")
        days = ", ".join(integrity["days"])
        st.caption(
            f"Archive days read: {days} (UTC). Evidence: "
            + ", ".join(f"`{where}{name}`" for name in integrity["files"])
            + "."
        )

    st.subheader("3 · Golden-reference parity")
    st.markdown(
        "The same rules were implemented a second time, independently, as **DuckDB SQL** over the "
        "raw archive (the *golden reference*). Each Spark result table must equal its golden "
        "counterpart."
    )
    parity = view["parity"]
    if not parity["available"]:
        _not_measured(
            "Golden-reference parity", "validation-silver.json / validation-gold.json", where
        )
    else:
        cols = st.columns(len(parity["layers"]))
        for col, layer in zip(cols, parity["layers"], strict=True):
            col.metric(
                f"{layer['layer'].title()} tables equal to golden",
                f"{layer['passed']} / {layer['total']}",
                border=True,
            )
        tables = frame(view["parity_tables"])
        with st.expander("Every table", icon=":material/table:"):
            st.dataframe(
                tables,
                hide_index=True,
                width="stretch",
                column_config={"Rows compared": st.column_config.NumberColumn(format="localized")},
            )
        with st.expander("Tolerance policy", icon=":material/rule:"):
            st.markdown(view["policy"])
        st.caption(
            "Parity shows that two independent implementations of the same written rules agree; "
            "it does not show that the rules themselves are the best possible definition. "
            f"Evidence: `{where}validation-silver.json`, `{where}validation-gold.json`."
        )

    st.subheader("4 · Automated tests")
    tests = view["tests"]
    if not tests["available"]:
        _not_measured("Recorded test results", tests["file"], where)
    else:
        left, right = st.columns(2)
        left.metric("Tests passed", f"{tests['passed']:,} / {tests['total']:,}", border=True)
        right.metric("Failed", f"{tests['failed']:,}", border=True)
        if tests["skipped"]:
            st.caption(f"{tests['skipped']} test(s) skipped in the recorded run.")
    st.caption(
        "The test suite (lint, type check, unit and integration tests: `python tasks.py check`) "
        "runs on every push in continuous integration; `python tasks.py test --record` writes the "
        f"counts to `{where}{tests['file']}`."
    )
    provenance_note()
