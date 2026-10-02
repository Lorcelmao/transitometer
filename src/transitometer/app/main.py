"""Transitometer app: was the promised transit service actually delivered?

Pages read the KPI tables through transitometer.serve.kpis, either from the Spark Gold layer
(TRANSITOMETER_APP_SOURCE=gold) or from the frozen golden reference (=golden, the default), and
the validation evidence from the committed results/*.json files (transitometer.serve.evidence).

Run: streamlit run src/transitometer/app/main.py
"""

from __future__ import annotations

import streamlit as st

from transitometer.app import diagnostics, overview, quality, reliability, scorecards

st.set_page_config(
    page_title="Transitometer · transit reliability",
    page_icon=":material/directions_bus:",
    layout="wide",
)

pages = {
    "home": st.Page(
        overview.page,
        title="Overview",
        icon=":material/dashboard:",
        default=True,
    ),
    "otp": st.Page(
        reliability.page_otp,
        title="On-time performance",
        icon=":material/schedule:",
        url_path="on-time",
    ),
    "headways": st.Page(
        reliability.page_headways,
        title="Headways and bunching",
        icon=":material/compare_arrows:",
        url_path="headways",
    ),
    "missing": st.Page(
        reliability.page_missing_trips,
        title="Missing trips",
        icon=":material/remove_road:",
        url_path="missing-trips",
    ),
    "scorecards": st.Page(
        scorecards.page_route_scorecards,
        title="Route scorecards",
        icon=":material/leaderboard:",
        url_path="route-scorecards",
    ),
    "stop": st.Page(
        scorecards.page_stop_reliability,
        title="Stop reliability",
        icon=":material/location_on:",
        url_path="stop-reliability",
    ),
    "delay": st.Page(
        diagnostics.page_delay_attribution,
        title="Where delay builds up",
        icon=":material/trending_up:",
        url_path="delay-attribution",
    ),
    "warning": st.Page(
        diagnostics.page_early_warning,
        title="Early warning",
        icon=":material/notifications_active:",
        url_path="early-warning",
    ),
    "feed": st.Page(
        quality.page_feed_health,
        title="Feed health",
        icon=":material/monitor_heart:",
        url_path="feed-health",
    ),
    "validation": st.Page(
        quality.page_validation,
        title="Data & validation",
        icon=":material/verified:",
        url_path="validation",
    ),
}
overview.LINKS.update(pages)

navigation = st.navigation(
    {
        "Start": [pages["home"]],
        "Reliability": [pages["otp"], pages["headways"], pages["missing"]],
        "Diagnostics": [pages["scorecards"], pages["stop"], pages["delay"], pages["warning"]],
        "Data quality": [pages["feed"], pages["validation"]],
    }
)
with st.sidebar:
    st.caption(
        "Real archived NYC bus and subway feeds, processed by a Kafka → Spark → Delta Lake "
        "pipeline and checked against an independent DuckDB reference."
    )
navigation.run()
