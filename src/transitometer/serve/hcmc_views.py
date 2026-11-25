"""Shared page views for BR11 (Ho Chi Minh City static bus network coverage).

Reads only the precomputed Parquet tables in showcase/data/hcmc/ with standard DuckDB (no
spatial extension needed at serving time), keeping Streamlit and the static Next.js site on
one set of numbers, labels, thresholds and display strings.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb

from transitometer.serve import kpis
from transitometer.serve.format import count, decimal, pct

Con = duckdb.DuckDBPyConnection
Row = dict[str, Any]

HCMC_DIR = kpis.SNAPSHOT_DIR / "hcmc"
HAND_CHECKS_PATH = kpis.REPO / "results" / "hcmc-hand-checks.json"
RANKED_WARDS = 15

SCOPES: dict[str, str] = {
    "core_hcmc": "Pre-merger HCMC (102 units, Res. 1685/NQ-UBTVQH15)",
    "merged_city_all": "Post-July-2025 merged HCMC (all 168 subareas)",
}
SHORT_SCOPES: dict[str, str] = {
    "core_hcmc": "Pre-merger HCMC (102)",
    "merged_city_all": "Merged city (168)",
}

HCMC_DEFINITIONS = (
    "- **Source:** OpenStreetMap (`© OpenStreetMap contributors, ODbL 1.0`, extracted offline from "
    "Geofabrik `vietnam-latest.osm.pbf`) bus route relations (`network = Xe buýt Thành phố Hồ Chí "
    "Minh`) converted to a frequency-based GTFS snapshot, joined to OSM post-July-2025 municipal "
    "ward/commune boundaries (`relation/1973756`, 168 subareas). Community open data — **not** an "
    "official agency timetable and **not** a live service.\n"
    "- **400 m walk-shed (M1 — % of natural land area, not % of population):** Each active stop "
    "is projected from `EPSG:4326` to metric `EPSG:32648` (UTM Zone 48N, `always_xy := true`), "
    "buffered by 400 m, and merged with `ST_Union_Agg` before intersecting each ward polygon so "
    "overlapping stop circles are never double-counted. The denominator is natural administrative "
    "area — including Cần Giờ mangrove forests, rivers, and waterways — so M1 measures **% of "
    "land area**, **not** `% of population`. Straight-line (Euclidean) 400 m is also more "
    "optimistic than street-network walking distance.\n"
    "- **Border-adjacent stops:** All active stops of `Xe buýt Thành phố Hồ Chí Minh` are kept in "
    "the 400 m buffer union before clipping to each ward polygon, so stops situated immediately "
    "outside a pre-merger ward boundary still contribute their 400 m walk-shed into neighboring "
    "border wards.\n"
    "- **Frequent service ≥ 4 buses/h (M2 — OSM `interval` only, no arrival times):** Because "
    "most HCMC OSM routes tag `interval` as a peak–off-peak range (e.g. `00:10-00:20`), M2 is "
    "derived solely from OSM `interval` tags by summing guaranteed minimum hourly departures "
    "`3600 / interval_max_s` across distinct serving route-directions (headline: conservative "
    "bound ≥ 4 buses/h, ≤ 15 min average wait; sensitivity: midpoint `interval_mid_s`). Because "
    "**0 %** of primary HCMC OSM bus relations carry a `duration` tag, derived `stop_times.txt` "
    "keeps stop order only — there are **no actual arrival times**, and schedule reliability "
    "cannot be measured without official GTFS-Realtime feeds.\n"
    "- **Two scopes:** `Pre-merger HCMC (102)` selects strictly the 102 commune-level units "
    "(78 wards + 24 communes) formed on pre-merger Ho Chi Minh City territory under National "
    "Assembly Standing Committee Resolution `1685/NQ-UBTVQH15` (16 Jun 2025, effective 1 Jul "
    "2025; OSM total ~2,058 km² vs official ~2,095 km², −1.8 % coastal/water-boundary difference); "
    "`Merged city (168)` covers all 168 post-July-2025 subareas including former Bình Dương (36) "
    "and Bà Rịa–Vũng Tàu (30) units served mainly by provincial bus networks outside "
    "`Xe buýt Thành phố Hồ Chí Minh`."
)


def _scan(path: Path) -> str:
    return "'" + path.as_posix().replace("'", "''") + "'"


def _rows(con: Con, sql: str, params: list[Any] | None = None) -> list[Row]:
    cur = con.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def load_hcmc_manifest(folder: Path = HCMC_DIR) -> Row | None:
    path = folder / "manifest.json"
    if not path.exists():
        return None
    data: Row = json.loads(path.read_text(encoding="utf-8"))
    return data


def _figure(
    key: str,
    label: str,
    value: Any,
    display: str,
    help_text: str | None = None,
    basis: str | None = None,
) -> Row:
    return {
        "key": key,
        "label": label,
        "value": value,
        "display": display,
        "help": help_text,
        "basis": basis,
    }


def _load_hand_checks(path: Path | None) -> list[Row]:
    if path is None or not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    routes = raw.get("routes", [])
    return list(routes) if isinstance(routes, list) else []


def hcmc_coverage(
    con: Con,
    folder: Path = HCMC_DIR,
    scope: str = "core_hcmc",
    hand_checks_path: Path | None = HAND_CHECKS_PATH,
) -> Row:
    """BR11 complete page view for one geographic scope ('core_hcmc' or 'merged_city_all')."""
    if scope not in SCOPES:
        raise ValueError(f"Unknown HCMC scope: {scope!r}")
    manifest = load_hcmc_manifest(folder)
    if manifest is None:
        return {
            "available": False,
            "scope": scope,
            "scope_label": SCOPES[scope],
            "figures": [],
            "definitions": HCMC_DEFINITIONS,
        }

    summary_rows = _rows(
        con,
        f"SELECT * FROM {_scan(folder / 'hcmc_summary.parquet')} WHERE scope = ?",
        [scope],
    )
    summary = summary_rows[0] if summary_rows else None
    where_scope = "WHERE in_core_hcmc = true" if scope == "core_hcmc" else ""
    ward_rows = _rows(
        con,
        f"""
        SELECT ward_id, osm_rel_id, ward_name, name_en, admin_level, in_core_hcmc,
               area_km2, covered_any_km2, coverage_any_400m_share,
               covered_freq_conservative_km2, coverage_freq_conservative_share,
               covered_freq_midpoint_km2, coverage_freq_midpoint_share,
               active_stops, frequent_stops_conservative, frequent_stops_midpoint,
               stops_per_km2, distinct_routes
        FROM {_scan(folder / "hcmc_ward_coverage.parquet")}
        {where_scope}
        ORDER BY coverage_any_400m_share ASC, area_km2 DESC, ward_id ASC
        """,
    )
    wards = [
        {
            **w,
            "coverage_any_display": pct(w["coverage_any_400m_share"]),
            "coverage_freq_cons_display": pct(w["coverage_freq_conservative_share"]),
            "coverage_freq_mid_display": pct(w["coverage_freq_midpoint_share"]),
            "area_display": f"{decimal(w['area_km2'], 2)} km²",
            "stops_per_km2_display": decimal(w["stops_per_km2"], 1),
        }
        for w in ward_rows
    ]
    bottom_wards = wards[:RANKED_WARDS]
    top_wards = sorted(
        wards,
        key=lambda w: (
            -w["coverage_any_400m_share"],
            -w["coverage_freq_conservative_share"],
            w["ward_id"],
        ),
    )[:RANKED_WARDS]

    route_rows = _rows(
        con,
        f"""
        SELECT route_ref, route_name, operator, directions, avg_stops_per_dir,
               avg_length_km, interval_min_min, interval_max_min,
               sample_interval, sample_opening_hours, is_ptv2_all, has_duration
        FROM {_scan(folder / "hcmc_route_summary.parquet")}
        ORDER BY avg_length_km DESC, route_ref ASC
        """,
    )
    quality_rows = _rows(
        con,
        f"""
        SELECT metric, label, value, numerator, denominator, threshold, passed, description
        FROM {_scan(folder / "hcmc_data_quality.parquet")}
        WHERE scope = 'hcmc_network'
        ORDER BY passed ASC, metric ASC
        """,
    )
    quality = [
        {
            **q,
            "value_display": pct(q["value"]),
            "threshold_display": f"≥ {pct(q['threshold'], 0)}",
            "ratio_display": f"{count(q['numerator'])} / {count(q['denominator'])}",
            "result": "passed" if q["passed"] else "below target",
        }
        for q in quality_rows
    ]
    passed_checks = sum(1 for q in quality if q["passed"])

    figures: list[Row] = []
    if summary is not None:
        figures = [
            _figure(
                "coverage_any",
                "Land area within 400 m of a bus stop",
                summary["coverage_any_400m_share"],
                pct(summary["coverage_any_400m_share"]),
                "Deduplicated 400 m walk-shed union (ST_Union_Agg on EPSG:32648) divided by "
                "natural administrative area (including Cần Giờ mangroves and waterways) — "
                "% of land area, not % of population.",
                f"{decimal(summary['covered_any_km2'], 1)} of "
                f"{decimal(summary['total_area_km2'], 1)} km² across {count(summary['wards'])} "
                "wards/communes",
            ),
            _figure(
                "coverage_freq",
                "Land area with ≥ 4 buses/h (conservative)",
                summary["coverage_freq_conservative_share"],
                pct(summary["coverage_freq_conservative_share"]),
                "Share of land area within 400 m of stops guaranteeing ≥ 4 departures/hour using "
                "OSM interval tags only (upper bound interval_max); 0% duration tagged so no "
                "actual arrival times exist.",
                f"midpoint sensitivity: {pct(summary['coverage_freq_midpoint_share'])} · "
                f"{count(summary['frequent_stops_conservative'])} frequent stops",
            ),
            _figure(
                "routes_mapped",
                "HCMC bus routes mapped",
                int(summary["distinct_routes"]),
                count(summary["distinct_routes"]),
                "Distinct route numbers (ref) tagged under Xe buýt Thành phố Hồ Chí Minh in OSM.",
                f"{count(summary['route_relations'])} directional relations · "
                f"{count(summary['active_stops'])} active stops in scope",
            ),
            _figure(
                "interval_coverage",
                "Routes with parsed headway",
                summary["interval_parsed_share"],
                pct(summary["interval_parsed_share"]),
                "Share of HCMC bus route relations whose OSM interval tag parsed cleanly into "
                "seconds (single value or peak–off-peak range).",
                f"PTv2: {pct(summary['ptv2_share'])} · duration tagged: "
                f"{pct(summary['duration_present_share'])} · "
                f"{passed_checks}/{len(quality)} checks passed",
            ),
        ]

    sources = manifest.get("sources", {})
    bus_src = sources.get("bus_routes", {}) if isinstance(sources, dict) else {}
    return {
        "available": True,
        "scope": scope,
        "scope_label": SCOPES[scope],
        "scopes": [{"key": k, "label": SCOPES[k], "short": SHORT_SCOPES[k]} for k in SCOPES],
        "summary": summary,
        "figures": figures,
        "wards": wards,
        "bottom_wards": bottom_wards,
        "top_wards": top_wards,
        "routes": route_rows,
        "quality": quality,
        "quality_passed": passed_checks,
        "quality_total": len(quality),
        "hand_checks": _load_hand_checks(hand_checks_path),
        "definitions": HCMC_DEFINITIONS,
        "provenance": {
            "schema": manifest.get("schema", "transitometer.hcmc/1"),
            "city": manifest.get("city", "Ho Chi Minh City"),
            "primary_network": manifest.get("primary_network", ""),
            "license": manifest.get("license", "OpenStreetMap contributors, ODbL 1.0"),
            "attribution": manifest.get("attribution", "© OpenStreetMap contributors (ODbL 1.0)"),
            "crs": manifest.get("crs", "EPSG:32648"),
            "walk_radius_m": manifest.get("walk_radius_m", 400.0),
            "frequent_buses_per_hour": manifest.get("frequent_buses_per_hour", 4.0),
            "retrieved_utc": bus_src.get("retrieved_utc", ""),
            "bus_sha256": str(bus_src.get("sha256", ""))[:12],
            "osm_city_timestamp": sources.get("osm_city_timestamp", "")
            if isinstance(sources, dict)
            else "",
            "tables": sorted(manifest.get("tables", {})),
        },
    }
