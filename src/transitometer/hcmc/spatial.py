"""DuckDB Spatial analytics for BR11: 400 m walk-shed coverage on EPSG:32648 (UTM Zone 48N).

Reads frequency-GTFS Parquet tables (Phase 1) and OSM ward polygons (relation/1973756 subareas),
computes deduplicated walk-shed area shares via ST_Transform(..., always_xy := true),
ST_Buffer, ST_Union_Agg and ST_Intersection, and writes precomputed Parquet outputs into
showcase/data/hcmc/ with an independent manifest (leaving MTA Spark Gold untouched).
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa

from transitometer.hcmc import BBox, CoreWardsSpec, HcmcConfig, normalize_ward_name
from transitometer.hcmc.quality import evaluate_quality

HCMC_SCHEMA = "transitometer.hcmc/1"
BUFFER_SEGMENTS = 16  # 16 segments per quadrant (64-gon: < 0.16 % area error vs exact pi*r^2)
HCMC_TABLES = (
    "hcmc_summary",
    "hcmc_ward_coverage",
    "hcmc_route_summary",
    "hcmc_stops",
    "hcmc_data_quality",
)


@dataclass(frozen=True)
class WardPolygon:
    ward_id: str
    osm_rel_id: int
    ward_name: str
    name_en: str
    admin_level: str
    geojson: str
    in_core_hcmc: bool


def connect_spatial() -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB with the spatial extension loaded (offline in Docker, cached on host)."""
    config: dict[str, Any] = {}
    ext_dir = os.environ.get("TRANSITOMETER_DUCKDB_EXT_DIR")
    if ext_dir:
        config["extension_directory"] = ext_dir
    con = duckdb.connect(config=config)
    try:
        con.execute("LOAD spatial")
    except duckdb.Error:
        con.execute("INSTALL spatial")
        con.execute("LOAD spatial")
    return con


def _pt_close(a: tuple[float, float], b: tuple[float, float], tol: float = 1e-7) -> bool:
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def stitch_rings(segments: list[list[tuple[float, float]]]) -> list[list[tuple[float, float]]]:
    """Connect unordered, arbitrarily oriented (lon, lat) way segments into closed rings."""
    remaining = [list(seg) for seg in segments if len(seg) >= 2]
    rings: list[list[tuple[float, float]]] = []
    while remaining:
        ring = remaining.pop(0)
        changed = True
        while changed and not _pt_close(ring[0], ring[-1]):
            changed = False
            for idx, seg in enumerate(remaining):
                if _pt_close(ring[-1], seg[0]):
                    ring.extend(seg[1:])
                    remaining.pop(idx)
                    changed = True
                    break
                if _pt_close(ring[-1], seg[-1]):
                    ring.extend(reversed(seg[:-1]))
                    remaining.pop(idx)
                    changed = True
                    break
                if _pt_close(ring[0], seg[-1]):
                    ring = seg[:-1] + ring
                    remaining.pop(idx)
                    changed = True
                    break
                if _pt_close(ring[0], seg[0]):
                    ring = list(reversed(seg[1:])) + ring
                    remaining.pop(idx)
                    changed = True
                    break
        if len(ring) >= 3:
            if not _pt_close(ring[0], ring[-1]):
                ring.append(ring[0])
            else:
                ring[-1] = ring[0]
            if len(ring) >= 4:
                rings.append(ring)
    return rings


def _ring_bbox(ring: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return min(xs), min(ys), max(xs), max(ys)


def _ring_area_signed(ring: list[tuple[float, float]]) -> float:
    total = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:], strict=False):
        total += x1 * y2 - x2 * y1
    return 0.5 * total


def build_multipolygon_geojson(
    outer_segments: list[list[tuple[float, float]]],
    inner_segments: list[list[tuple[float, float]]],
) -> str | None:
    """Assemble OSM outer/inner boundary way lists into a GeoJSON MultiPolygon string."""
    outers = stitch_rings(outer_segments)
    if not outers:
        return None
    inners = stitch_rings(inner_segments)
    # Sort largest outer ring first for deterministic output and inner assignment.
    outers.sort(key=lambda r: abs(_ring_area_signed(r)), reverse=True)
    outer_boxes = [_ring_bbox(r) for r in outers]
    polys: list[list[list[list[float]]]] = [[[[p[0], p[1]] for p in r]] for r in outers]
    for hole in inners:
        hx0, hy0, hx1, hy1 = _ring_bbox(hole)
        target = 0
        for idx, (ox0, oy0, ox1, oy1) in enumerate(outer_boxes):
            if ox0 <= hx0 and oy0 <= hy0 and ox1 >= hx1 and oy1 >= hy1:
                target = idx
                break
        polys[target].append([[p[0], p[1]] for p in hole])
    geom = {"type": "MultiPolygon", "coordinates": polys}
    return json.dumps(geom, separators=(",", ":"))


def wards_from_osm(
    osm_wards_doc: dict[str, Any],
    core_bbox: BBox,
    core_ward_names: frozenset[str] | set[str] | None = None,
) -> list[WardPolygon]:
    """Parse OSM ward/commune relations (with embedded `out geom` ways) into WardPolygons.

    When `core_ward_names` is supplied (from config/hcmc_core_wards.json, Res. 1685/NQ-UBTVQH15),
    membership in `core_hcmc` is determined strictly by normalized Vietnamese name match.
    The `core_bbox` fallback is used only when `core_ward_names` is omitted (e.g. synthetic tests).
    """
    normalized_core = (
        {normalize_ward_name(n) for n in core_ward_names} if core_ward_names is not None else None
    )
    wards: list[WardPolygon] = []
    elements = sorted(
        (e for e in osm_wards_doc.get("elements", []) if e.get("type") == "relation"),
        key=lambda e: int(e["id"]),
    )
    for rel in elements:
        rel_id = int(rel["id"])
        tags = rel.get("tags", {})
        outer_segs: list[list[tuple[float, float]]] = []
        inner_segs: list[list[tuple[float, float]]] = []
        all_lats: list[float] = []
        all_lons: list[float] = []
        for m in rel.get("members", []):
            if m.get("type") != "way":
                continue
            geom = m.get("geometry")
            if not isinstance(geom, list) or len(geom) < 2:
                continue
            pts = [(float(p["lon"]), float(p["lat"])) for p in geom if "lat" in p and "lon" in p]
            if len(pts) < 2:
                continue
            role = str(m.get("role", "")).strip()
            if role == "inner":
                inner_segs.append(pts)
            else:
                outer_segs.append(pts)
                all_lons.extend(p[0] for p in pts)
                all_lats.extend(p[1] for p in pts)
        geojson = build_multipolygon_geojson(outer_segs, inner_segs)
        if geojson is None or not all_lats:
            continue
        clat = 0.5 * (min(all_lats) + max(all_lats))
        clon = 0.5 * (min(all_lons) + max(all_lons))
        ward_name = normalize_ward_name(str(tags.get("name", f"Ward {rel_id}")))
        in_core = (
            ward_name in normalized_core
            if normalized_core is not None
            else core_bbox.contains(clat, clon)
        )
        wards.append(
            WardPolygon(
                ward_id=f"rel_{rel_id}",
                osm_rel_id=rel_id,
                ward_name=ward_name,
                name_en=str(tags.get("name:en", "")).strip(),
                admin_level=str(tags.get("admin_level", "6")).strip(),
                geojson=geojson,
                in_core_hcmc=in_core,
            )
        )
    return wards


def audit_core_ward_matching(wards: list[WardPolygon], core_spec: CoreWardsSpec) -> dict[str, Any]:
    """Compare parsed OSM wards against the official pre-merger HCMC ward list."""
    osm_names = {normalize_ward_name(w.ward_name) for w in wards}
    matched = [n for n in core_spec.ordered_names if n in osm_names]
    missing = [n for n in core_spec.ordered_names if n not in osm_names]
    non_core = sorted(n for n in osm_names if n not in core_spec.ward_names)
    return {
        "resolution": core_spec.resolution,
        "resolution_date": core_spec.resolution_date,
        "official_pre_merger_area_km2": core_spec.official_pre_merger_area_km2,
        "expected": len(core_spec.ordered_names),
        "matched": len(matched),
        "missing_from_osm": missing,
        "non_core_osm_count": len(non_core),
        "total_osm_wards": len(wards),
    }


def _scan(path: Path) -> str:
    return "'" + path.as_posix().replace("'", "''") + "'"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _export_query(con: duckdb.DuckDBPyConnection, sql: str, dest: Path) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"COPY ({sql}) TO {_scan(dest)} (FORMAT parquet)")
    row = con.execute(f"SELECT count(*) FROM {_scan(dest)}").fetchone()
    return int(row[0]) if row else 0


def compute_coverage(
    gtfs_dir: Path,
    wards: list[WardPolygon],
    cfg: HcmcConfig,
    out_dir: Path,
    source_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute M1–M3 coverage metrics in DuckDB Spatial and write showcase/data/hcmc/."""
    if not wards:
        raise ValueError("No valid ward polygons provided")

    out_dir.mkdir(parents=True, exist_ok=True)
    quality_rows = evaluate_quality(gtfs_dir, out_dir / "hcmc_data_quality.parquet")

    routes_p = _scan(gtfs_dir / "routes.parquet")
    stops_p = _scan(gtfs_dir / "stops.parquet")
    trips_p = _scan(gtfs_dir / "trips.parquet")
    st_p = _scan(gtfs_dir / "stop_times.parquet")
    freq_p = _scan(gtfs_dir / "frequencies.parquet")
    shapes_p = _scan(gtfs_dir / "shapes.parquet")

    # Build a small Arrow table of ward polygons to register directly in DuckDB.
    wards_arrow = pa.table(
        {
            "ward_id": [w.ward_id for w in wards],
            "osm_rel_id": [w.osm_rel_id for w in wards],
            "ward_name": [w.ward_name for w in wards],
            "name_en": [w.name_en for w in wards],
            "admin_level": [w.admin_level for w in wards],
            "geojson": [w.geojson for w in wards],
            "in_core_hcmc": [w.in_core_hcmc for w in wards],
        }
    )

    radius_m = float(cfg.walk_radius_m)
    freq_bar = float(cfg.frequent_buses_per_hour)
    crs = cfg.crs

    with connect_spatial() as con:
        con.register("raw_wards", wards_arrow)

        # 1. Valid ward polygons projected to metric CRS (EPSG:32648, always_xy := true).
        con.execute(
            f"""
            CREATE TEMP TABLE wards_utm AS
            WITH parsed AS (
                SELECT
                    ward_id,
                    osm_rel_id,
                    ward_name,
                    name_en,
                    admin_level,
                    in_core_hcmc,
                    ST_MakeValid(
                        ST_Transform(
                            ST_MakeValid(ST_GeomFromGeoJSON(geojson)),
                            'EPSG:4326',
                            '{crs}',
                            always_xy := true
                        )
                    ) AS geom_utm
                FROM raw_wards
            )
            SELECT
                ward_id,
                osm_rel_id,
                ward_name,
                name_en,
                admin_level,
                in_core_hcmc,
                geom_utm,
                ST_Area(geom_utm) / 1e6 AS area_km2,
                ST_X(ST_Centroid(geom_utm)) AS cx_utm,
                ST_Y(ST_Centroid(geom_utm)) AS cy_utm
            FROM parsed
            WHERE geom_utm IS NOT NULL AND ST_Area(geom_utm) > 0
            """
        )

        # 2. Active HCMC stops with deduplicated per-(route_ref, direction) service frequency.
        con.execute(
            f"""
            CREATE TEMP TABLE active_stops_utm AS
            WITH per_route_dir AS (
                SELECT
                    st.stop_id,
                    coalesce(nullif(r.route_short_name, ''), r.route_id) AS route_ref,
                    t.direction_id,
                    max(CASE WHEN f.interval_max_s IS NOT NULL
                             THEN 3600.0 / f.interval_max_s END) AS bph_min,
                    max(CASE WHEN f.interval_mid_s IS NOT NULL
                             THEN 3600.0 / f.interval_mid_s END) AS bph_mid,
                    max(CASE WHEN f.interval_min_s IS NOT NULL
                             THEN 3600.0 / f.interval_min_s END) AS bph_max
                FROM read_parquet({routes_p}) r
                JOIN read_parquet({trips_p}) t ON t.route_id = r.route_id
                JOIN read_parquet({st_p}) st ON st.trip_id = t.trip_id
                LEFT JOIN read_parquet({freq_p}) f ON f.trip_id = t.trip_id
                WHERE r.is_hcmc_network = true
                GROUP BY 1, 2, 3
            ),
            agg AS (
                SELECT
                    stop_id,
                    count(DISTINCT route_ref)::INTEGER AS route_count,
                    count(*)::INTEGER AS direction_count,
                    coalesce(sum(bph_min), 0.0) AS buses_per_hour_min,
                    coalesce(sum(bph_mid), 0.0) AS buses_per_hour_mid,
                    coalesce(sum(bph_max), 0.0) AS buses_per_hour_max
                FROM per_route_dir
                GROUP BY stop_id
            ),
            pts AS (
                SELECT
                    s.stop_id,
                    s.stop_name,
                    s.stop_lat,
                    s.stop_lon,
                    a.route_count,
                    a.direction_count,
                    round(a.buses_per_hour_min, 3) AS buses_per_hour_min,
                    round(a.buses_per_hour_mid, 3) AS buses_per_hour_mid,
                    round(a.buses_per_hour_max, 3) AS buses_per_hour_max,
                    (a.buses_per_hour_min >= {freq_bar}) AS is_frequent_conservative,
                    (a.buses_per_hour_mid >= {freq_bar}) AS is_frequent_midpoint,
                    ST_Transform(
                        ST_Point(s.stop_lon, s.stop_lat),
                        'EPSG:4326',
                        '{crs}',
                        always_xy := true
                    ) AS geom_utm
                FROM agg a
                JOIN read_parquet({stops_p}) s ON s.stop_id = a.stop_id
                WHERE s.in_bbox = true
            ),
            with_ward AS (
                SELECT
                    p.*,
                    w.ward_id,
                    row_number() OVER (PARTITION BY p.stop_id ORDER BY w.ward_id NULLS LAST) AS rn
                FROM pts p
                LEFT JOIN wards_utm w ON ST_Contains(w.geom_utm, p.geom_utm)
            )
            SELECT
                stop_id,
                stop_name,
                stop_lat,
                stop_lon,
                route_count,
                direction_count,
                buses_per_hour_min,
                buses_per_hour_mid,
                buses_per_hour_max,
                is_frequent_conservative,
                is_frequent_midpoint,
                ward_id,
                geom_utm,
                ST_Buffer(geom_utm, {radius_m}, {BUFFER_SEGMENTS}) AS buf_utm
            FROM with_ward
            WHERE rn = 1
            """
        )

        # 3. Ward-level M1, M2, M3 coverage metrics.
        con.execute(
            f"""
            CREATE TEMP TABLE ward_coverage AS
            WITH nearby AS (
                SELECT
                    w.ward_id,
                    s.stop_id,
                    s.buf_utm,
                    s.is_frequent_conservative,
                    s.is_frequent_midpoint
                FROM wards_utm w
                JOIN active_stops_utm s
                  ON ST_DWithin(w.geom_utm, s.geom_utm, {radius_m})
            ),
            unions AS (
                SELECT
                    ward_id,
                    ST_Union_Agg(buf_utm) AS u_any,
                    ST_Union_Agg(buf_utm) FILTER (WHERE is_frequent_conservative) AS u_freq_cons,
                    ST_Union_Agg(buf_utm) FILTER (WHERE is_frequent_midpoint) AS u_freq_mid
                FROM nearby
                GROUP BY ward_id
            ),
            inside_stops AS (
                SELECT
                    ward_id,
                    count(*)::INTEGER AS active_stops,
                    count(*) FILTER (WHERE is_frequent_conservative)::INTEGER
                        AS frequent_stops_conservative,
                    count(*) FILTER (WHERE is_frequent_midpoint)::INTEGER
                        AS frequent_stops_midpoint
                FROM active_stops_utm
                WHERE ward_id IS NOT NULL
                GROUP BY ward_id
            ),
            ward_routes AS (
                SELECT
                    s.ward_id,
                    count(DISTINCT coalesce(nullif(r.route_short_name, ''), r.route_id))::INTEGER
                        AS distinct_routes
                FROM active_stops_utm s
                JOIN read_parquet({st_p}) st ON st.stop_id = s.stop_id
                JOIN read_parquet({trips_p}) t ON t.trip_id = st.trip_id
                JOIN read_parquet({routes_p}) r ON r.route_id = t.route_id
                WHERE s.ward_id IS NOT NULL AND r.is_hcmc_network = true
                GROUP BY s.ward_id
            ),
            areas AS (
                SELECT
                    w.ward_id,
                    w.osm_rel_id,
                    w.ward_name,
                    w.name_en,
                    w.admin_level,
                    w.in_core_hcmc,
                    w.area_km2,
                    coalesce(
                        CASE WHEN u.u_any IS NOT NULL
                             THEN ST_Area(ST_Intersection(w.geom_utm, u.u_any)) / 1e6 END,
                        0.0
                    ) AS raw_any_km2,
                    coalesce(
                        CASE WHEN u.u_freq_cons IS NOT NULL
                             THEN ST_Area(ST_Intersection(w.geom_utm, u.u_freq_cons)) / 1e6 END,
                        0.0
                    ) AS raw_freq_cons_km2,
                    coalesce(
                        CASE WHEN u.u_freq_mid IS NOT NULL
                             THEN ST_Area(ST_Intersection(w.geom_utm, u.u_freq_mid)) / 1e6 END,
                        0.0
                    ) AS raw_freq_mid_km2,
                    coalesce(i.active_stops, 0) AS active_stops,
                    coalesce(i.frequent_stops_conservative, 0) AS frequent_stops_conservative,
                    coalesce(i.frequent_stops_midpoint, 0) AS frequent_stops_midpoint,
                    coalesce(wr.distinct_routes, 0) AS distinct_routes
                FROM wards_utm w
                LEFT JOIN unions u ON u.ward_id = w.ward_id
                LEFT JOIN inside_stops i ON i.ward_id = w.ward_id
                LEFT JOIN ward_routes wr ON wr.ward_id = w.ward_id
            )
            SELECT
                ward_id,
                osm_rel_id,
                ward_name,
                name_en,
                admin_level,
                in_core_hcmc,
                round(area_km2, 4) AS area_km2,
                round(least(area_km2, raw_any_km2), 4) AS covered_any_km2,
                round(least(1.0, greatest(0.0, raw_any_km2 / area_km2)), 6)
                    AS coverage_any_400m_share,
                round(least(area_km2, raw_freq_cons_km2), 4) AS covered_freq_conservative_km2,
                round(least(1.0, greatest(0.0, raw_freq_cons_km2 / area_km2)), 6)
                    AS coverage_freq_conservative_share,
                round(least(area_km2, raw_freq_mid_km2), 4) AS covered_freq_midpoint_km2,
                round(least(1.0, greatest(0.0, raw_freq_mid_km2 / area_km2)), 6)
                    AS coverage_freq_midpoint_share,
                active_stops,
                frequent_stops_conservative,
                frequent_stops_midpoint,
                round(active_stops / area_km2, 3) AS stops_per_km2,
                distinct_routes
            FROM areas
            ORDER BY ward_id
            """
        )

        # 4. Route-level summary (prefer exact OSM way-sum length; fallback to UTM ST_Length).
        con.execute(
            f"""
            CREATE TEMP TABLE route_summary AS
            WITH shape_lines AS (
                SELECT
                    shape_id,
                    ST_Length(
                        ST_Transform(
                            ST_MakeLine(
                                list(ST_Point(shape_pt_lon, shape_pt_lat)
                                     ORDER BY shape_pt_sequence)
                            ),
                            'EPSG:4326',
                            '{crs}',
                            always_xy := true
                        )
                    ) / 1000.0 AS utm_length_km
                FROM read_parquet({shapes_p})
                GROUP BY shape_id
                HAVING count(*) >= 2
            ),
            per_rel AS (
                SELECT
                    r.route_id,
                    coalesce(nullif(r.route_short_name, ''), r.route_id) AS route_ref,
                    r.route_long_name,
                    r.operator,
                    r.is_ptv2,
                    r.has_duration,
                    r.opening_hours_raw,
                    CASE
                        WHEN r.shape_length_km IS NOT NULL AND r.shape_length_km > 0
                        THEN r.shape_length_km
                        ELSE sl.utm_length_km
                    END AS length_km,
                    f.interval_raw,
                    f.interval_min_s,
                    f.interval_mid_s,
                    f.interval_max_s,
                    (SELECT count(DISTINCT st.stop_id)
                     FROM read_parquet({st_p}) st
                     JOIN read_parquet({stops_p}) s USING (stop_id)
                     WHERE st.trip_id = t.trip_id AND s.in_bbox) AS stops_in_dir
                FROM read_parquet({routes_p}) r
                JOIN read_parquet({trips_p}) t ON t.route_id = r.route_id
                LEFT JOIN read_parquet({freq_p}) f ON f.trip_id = t.trip_id
                LEFT JOIN shape_lines sl ON sl.shape_id = t.shape_id
                WHERE r.is_hcmc_network = true
            )
            SELECT
                route_ref,
                min(route_long_name) AS route_name,
                min(operator) AS operator,
                count(*)::INTEGER AS directions,
                round(avg(stops_in_dir), 1) AS avg_stops_per_dir,
                round(avg(length_km), 2) AS avg_length_km,
                round(min(interval_min_s) / 60.0, 1) AS interval_min_min,
                round(max(interval_max_s) / 60.0, 1) AS interval_max_min,
                min(nullif(interval_raw, '')) AS sample_interval,
                min(nullif(opening_hours_raw, '')) AS sample_opening_hours,
                bool_and(is_ptv2) AS is_ptv2_all,
                bool_or(has_duration) AS has_duration
            FROM per_rel
            GROUP BY route_ref
            ORDER BY route_ref
            """
        )

        # 5. Network-level additive summary for both scopes (core_hcmc vs merged_city_all).
        hcmc_q = {r["metric"]: r["value"] for r in quality_rows if r["scope"] == "hcmc_network"}
        interval_cov = float(hcmc_q.get("interval_parsed_share", 0.0))
        ptv2_cov = float(hcmc_q.get("ptv2_share", 0.0))
        dur_cov = float(hcmc_q.get("duration_present_share", 0.0))

        con.execute(
            f"""
            CREATE TEMP TABLE hcmc_summary AS
            WITH route_totals AS (
                SELECT
                    count(*)::INTEGER AS distinct_routes,
                    coalesce(sum(directions), 0)::INTEGER AS route_relations
                FROM route_summary
            ),
            scoped AS (
                SELECT 'core_hcmc' AS scope, * FROM ward_coverage WHERE in_core_hcmc = true
                UNION ALL
                SELECT 'merged_city_all' AS scope, * FROM ward_coverage
            )
            SELECT
                s.scope,
                count(*)::INTEGER AS wards,
                count(*) FILTER (WHERE s.active_stops > 0)::INTEGER AS wards_with_stops,
                round(sum(s.area_km2), 2) AS total_area_km2,
                round(sum(s.covered_any_km2), 2) AS covered_any_km2,
                round(
                    CASE WHEN sum(s.area_km2) > 0
                         THEN sum(s.covered_any_km2) / sum(s.area_km2) ELSE 0.0 END,
                    6
                ) AS coverage_any_400m_share,
                round(sum(s.covered_freq_conservative_km2), 2) AS covered_freq_conservative_km2,
                round(
                    CASE WHEN sum(s.area_km2) > 0
                         THEN sum(s.covered_freq_conservative_km2) / sum(s.area_km2) ELSE 0.0 END,
                    6
                ) AS coverage_freq_conservative_share,
                round(sum(s.covered_freq_midpoint_km2), 2) AS covered_freq_midpoint_km2,
                round(
                    CASE WHEN sum(s.area_km2) > 0
                         THEN sum(s.covered_freq_midpoint_km2) / sum(s.area_km2) ELSE 0.0 END,
                    6
                ) AS coverage_freq_midpoint_share,
                coalesce(sum(s.active_stops), 0)::INTEGER AS active_stops,
                coalesce(sum(s.frequent_stops_conservative), 0)::INTEGER
                    AS frequent_stops_conservative,
                coalesce(sum(s.frequent_stops_midpoint), 0)::INTEGER
                    AS frequent_stops_midpoint,
                rt.distinct_routes,
                rt.route_relations,
                {interval_cov}::DOUBLE AS interval_parsed_share,
                {ptv2_cov}::DOUBLE AS ptv2_share,
                {dur_cov}::DOUBLE AS duration_present_share
            FROM scoped s
            CROSS JOIN route_totals rt
            GROUP BY s.scope, rt.distinct_routes, rt.route_relations
            ORDER BY s.scope
            """
        )

        # Write all 4 spatial Parquet outputs deterministically.
        counts: dict[str, int] = {}
        counts["hcmc_summary"] = _export_query(
            con, "SELECT * FROM hcmc_summary ORDER BY scope", out_dir / "hcmc_summary.parquet"
        )
        counts["hcmc_ward_coverage"] = _export_query(
            con,
            "SELECT * FROM ward_coverage ORDER BY ward_id",
            out_dir / "hcmc_ward_coverage.parquet",
        )
        counts["hcmc_route_summary"] = _export_query(
            con,
            "SELECT * FROM route_summary ORDER BY route_ref",
            out_dir / "hcmc_route_summary.parquet",
        )
        counts["hcmc_stops"] = _export_query(
            con,
            """
            SELECT stop_id, stop_name, stop_lat, stop_lon, route_count, direction_count,
                   buses_per_hour_min, buses_per_hour_mid, buses_per_hour_max,
                   is_frequent_conservative, is_frequent_midpoint, ward_id
            FROM active_stops_utm
            ORDER BY stop_id
            """,
            out_dir / "hcmc_stops.parquet",
        )
        counts["hcmc_data_quality"] = len(quality_rows)

    tables_manifest: dict[str, dict[str, Any]] = {}
    for name in HCMC_TABLES:
        path = out_dir / f"{name}.parquet"
        tables_manifest[name] = {
            "rows": counts[name],
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }

    manifest = {
        "schema": HCMC_SCHEMA,
        "city": cfg.city,
        "primary_network": cfg.primary_network,
        "license": cfg.license,
        "attribution": cfg.attribution,
        "crs": cfg.crs,
        "walk_radius_m": cfg.walk_radius_m,
        "frequent_buses_per_hour": cfg.frequent_buses_per_hour,
        "sources": source_meta or {},
        "tables": tables_manifest,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest
