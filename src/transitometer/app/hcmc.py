"""Case study (BR11): Ho Chi Minh City static bus network coverage (U7).

Reads precomputed Parquet outputs from showcase/data/hcmc/ via transitometer.serve.hcmc_views
using standard DuckDB (no spatial extension needed at runtime on Streamlit Community Cloud).
"""

from __future__ import annotations

import altair as alt
import duckdb
import pandas as pd
import streamlit as st

from transitometer.app import common
from transitometer.serve import hcmc_views


def page_hcmc() -> None:
    st.title("Where does Ho Chi Minh City's bus network leave coverage gaps?")
    st.caption(
        "Case study for U7 (HCMC transit planner, BR11): static 400 m walk-shed coverage computed "
        "in DuckDB Spatial (`EPSG:32648`) from OpenStreetMap bus routes and post-July-2025 ward "
        "boundaries."
    )

    left, right = st.columns([1, 1])
    scope = (
        left.segmented_control(
            "Geographic scope",
            list(hcmc_views.SCOPES),
            format_func=hcmc_views.SHORT_SCOPES.get,
            default="core_hcmc",
            key="hcmc-scope",
        )
        or "core_hcmc"
    )
    metric_mode = (
        right.segmented_control(
            "Coverage layer",
            ["any", "freq_cons", "freq_mid"],
            format_func={
                "any": "Any bus stop (400 m)",
                "freq_cons": "Frequent ≥ 4/h (conservative)",
                "freq_mid": "Frequent ≥ 4/h (midpoint)",
            }.get,
            default="any",
            key="hcmc-metric",
        )
        or "any"
    )

    with duckdb.connect() as con:
        view = hcmc_views.hcmc_coverage(con, hcmc_views.HCMC_DIR, scope=scope)

    if not view.get("available"):
        st.info("No HCMC case-study snapshot found yet (`python tasks.py hcmc-build`).")
        return

    cols = st.columns(len(view["figures"]))
    for col, fig in zip(cols, view["figures"], strict=True):
        col.metric(fig["label"], fig["display"], help=fig.get("help"))
        if fig.get("basis"):
            col.caption(fig["basis"])

    st.info(
        "Scope & limitations: **Pre-merger HCMC (102)** uses the 102 commune-level units defined "
        "by Resolution 1685/NQ-UBTVQH15 (16 Jun 2025). M1 divides walk-shed area by natural "
        "administrative area (including Cần Giờ mangroves and waterways), so it measures **% of "
        "land area**, not **% of population**. M2 relies solely on OSM `interval` tags (0 % "
        "`duration` tagged, so no actual arrival times). All active HCMC bus stops are buffered "
        "before clipping so border-adjacent stops still cover neighboring wards."
    )

    metric_col, metric_title = {
        "any": ("coverage_any_400m_share", "Area within 400 m of any bus stop"),
        "freq_cons": (
            "coverage_freq_conservative_share",
            "Area within 400 m of ≥ 4 buses/h stops (conservative)",
        ),
        "freq_mid": (
            "coverage_freq_midpoint_share",
            "Area within 400 m of ≥ 4 buses/h stops (midpoint)",
        ),
    }[metric_mode]

    wards_df = pd.DataFrame(view["wards"])
    if not wards_df.empty:
        col_low, col_high = st.columns(2)
        with col_low:
            st.subheader("Wards with the largest coverage gaps")
            low = wards_df.sort_values([metric_col, "area_km2"], ascending=[True, False]).head(
                hcmc_views.RANKED_WARDS
            )
            chart_low = (
                alt.Chart(low, height=max(220, 26 * len(low)))
                .mark_bar(color="#dc2626", cornerRadiusEnd=4, height={"band": 0.7})
                .encode(
                    x=alt.X(
                        f"{metric_col}:Q",
                        title=metric_title,
                        scale=alt.Scale(domain=[0, 1]),
                        axis=alt.Axis(format="%", grid=True),
                    ),
                    y=alt.Y("ward_name:N", sort=None, title="Ward / Commune"),
                    tooltip=[
                        "ward_name",
                        alt.Tooltip("area_km2:Q", format=".2f", title="Area (km²)"),
                        alt.Tooltip(f"{metric_col}:Q", format=".1%", title="Coverage"),
                        alt.Tooltip("active_stops:Q", title="Active stops"),
                        alt.Tooltip("distinct_routes:Q", title="Routes"),
                    ],
                )
            )
            st.altair_chart(chart_low, width="stretch")

        with col_high:
            st.subheader("Best-covered wards")
            high = wards_df.sort_values(
                [metric_col, "distinct_routes"], ascending=[False, False]
            ).head(hcmc_views.RANKED_WARDS)
            chart_high = (
                alt.Chart(high, height=max(220, 26 * len(high)))
                .mark_bar(color=common.BLUE, cornerRadiusEnd=4, height={"band": 0.7})
                .encode(
                    x=alt.X(
                        f"{metric_col}:Q",
                        title=metric_title,
                        scale=alt.Scale(domain=[0, 1]),
                        axis=alt.Axis(format="%", grid=True),
                    ),
                    y=alt.Y("ward_name:N", sort=None, title="Ward / Commune"),
                    tooltip=[
                        "ward_name",
                        alt.Tooltip("area_km2:Q", format=".2f", title="Area (km²)"),
                        alt.Tooltip(f"{metric_col}:Q", format=".1%", title="Coverage"),
                        alt.Tooltip("active_stops:Q", title="Active stops"),
                        alt.Tooltip("distinct_routes:Q", title="Routes"),
                    ],
                )
            )
            st.altair_chart(chart_high, width="stretch")

        st.subheader("Ward-by-ward coverage table")
        display_df = wards_df[
            [
                "ward_name",
                "area_display",
                "coverage_any_display",
                "coverage_freq_cons_display",
                "coverage_freq_mid_display",
                "active_stops",
                "stops_per_km2_display",
                "distinct_routes",
            ]
        ].rename(
            columns={
                "ward_name": "Ward / Commune",
                "area_display": "Area",
                "coverage_any_display": "400 m (any)",
                "coverage_freq_cons_display": "≥ 4/h (conservative)",
                "coverage_freq_mid_display": "≥ 4/h (midpoint)",
                "active_stops": "Stops",
                "stops_per_km2_display": "Stops / km²",
                "distinct_routes": "Routes",
            }
        )
        st.dataframe(display_df, width="stretch", hide_index=True)

    st.subheader("OpenStreetMap data quality checks (BR7 counterpart)")
    q_df = pd.DataFrame(view["quality"])
    if not q_df.empty:
        st.caption(
            f"{view['quality_passed']} of {view['quality_total']} open-data completeness checks "
            "passed on `Xe buýt Thành phố Hồ Chí Minh`."
        )
        st.dataframe(
            q_df[["label", "value_display", "ratio_display", "threshold_display", "result"]].rename(
                columns={
                    "label": "Check",
                    "value_display": "Measured",
                    "ratio_display": "Count",
                    "threshold_display": "Target",
                    "result": "Status",
                }
            ),
            width="stretch",
            hide_index=True,
        )

    if view["routes"]:
        st.subheader("Mapped HCMC bus routes (OSM-derived)")
        routes_df = pd.DataFrame(view["routes"])
        flagged_n = int(routes_df["osm_incomplete"].sum())
        st.caption(
            f"{len(routes_df)} distinct routes in `Xe buýt Thành phố Hồ Chí Minh`. "
            f"{flagged_n} route(s) are marked **Incomplete OSM data** instead of "
            "displaying unreliable OSM way sums (endpoint-only stop mapping or unverified "
            "corridor detours above 120 km); stop-based walk-shed coverage is unaffected."
        )
        route_display = routes_df[
            [
                "route_ref",
                "route_name",
                "directions",
                "avg_stops_per_dir",
                "length_display",
                "sample_interval",
                "osm_note",
            ]
        ].rename(
            columns={
                "route_ref": "Route",
                "route_name": "Corridor",
                "directions": "Dirs",
                "avg_stops_per_dir": "Mapped stops / dir",
                "length_display": "Length",
                "sample_interval": "OSM interval",
                "osm_note": "OSM data note",
            }
        )
        st.dataframe(route_display, width="stretch", hide_index=True)

    if view["hand_checks"]:
        st.subheader("Manual cross-check against official HCMC bus information")
        st.dataframe(pd.DataFrame(view["hand_checks"]), width="stretch", hide_index=True)

    common.definitions(view["definitions"])
    prov = view["provenance"]
    st.divider()
    st.caption(
        f"Data: static OpenStreetMap snapshot ({prov['attribution']}, fetched "
        f"{prov['retrieved_utc'] or 'pinned'}) processed with DuckDB Spatial ({prov['crs']}, "
        f"{int(prov['walk_radius_m'])} m buffer); not a live service and not an official agency "
        "timetable."
    )
