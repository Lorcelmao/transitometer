"""Analytical geometry tests for BR11 DuckDB Spatial coverage (EPSG:32648, UTM Zone 48N)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from transitometer.hcmc import load_config, load_core_wards
from transitometer.hcmc.osm_to_gtfs import (
    FREQUENCIES_SCHEMA,
    ROUTES_SCHEMA,
    SHAPES_SCHEMA,
    STOP_TIMES_SCHEMA,
    STOPS_SCHEMA,
    TRIPS_SCHEMA,
)
from transitometer.hcmc.spatial import (
    WardPolygon,
    audit_core_ward_matching,
    build_multipolygon_geojson,
    compute_coverage,
    connect_spatial,
    stitch_rings,
    wards_from_osm,
)

# Reference UTM Zone 48N coordinate in central Ho Chi Minh City (meters).
BASE_E = 685_000.0
BASE_N = 1_191_000.0


def _utm_to_wgs84(con: duckdb.DuckDBPyConnection, x: float, y: float) -> tuple[float, float]:
    """Return (lon, lat) in WGS84 for an EPSG:32648 meter coordinate."""
    row = con.execute(
        f"SELECT ST_X(p), ST_Y(p) FROM ("
        f"SELECT ST_Transform(ST_Point({x}, {y}), 'EPSG:32648', 'EPSG:4326', "
        f"always_xy := true) AS p)"
    ).fetchone()
    assert row is not None
    return float(row[0]), float(row[1])


def _square_ward(
    con: duckdb.DuckDBPyConnection,
    ward_id: str,
    x0: float,
    y0: float,
    size_m: float,
    in_core: bool = True,
) -> WardPolygon:
    corners_utm = [
        (x0, y0),
        (x0 + size_m, y0),
        (x0 + size_m, y0 + size_m),
        (x0, y0 + size_m),
        (x0, y0),
    ]
    ring = [list(_utm_to_wgs84(con, x, y)) for x, y in corners_utm]
    geojson = json.dumps({"type": "MultiPolygon", "coordinates": [[ring]]}, separators=(",", ":"))
    return WardPolygon(
        ward_id=ward_id,
        osm_rel_id=int(ward_id.split("_")[-1]),
        ward_name=f"Synthetic {ward_id}",
        name_en="",
        admin_level="6",
        geojson=geojson,
        in_core_hcmc=in_core,
    )


def _write_synthetic_gtfs(
    gtfs_dir: Path,
    stops: list[tuple[str, float, float]],  # (stop_id, lon, lat)
    routes_intervals: list[tuple[str, str, int, int, int, list[str]]],
    # (route_ref, route_id, min_s, mid_s, max_s, stop_ids)
) -> None:
    gtfs_dir.mkdir(parents=True, exist_ok=True)
    routes: list[dict[str, object]] = []
    trips: list[dict[str, object]] = []
    stop_times: list[dict[str, object]] = []
    freqs: list[dict[str, object]] = []
    shapes: list[dict[str, object]] = []
    for ref, rid, lo, mid, hi, sids in routes_intervals:
        tid = f"t_{rid}"
        routes.append(
            {
                "route_id": rid,
                "agency_id": "AG_TEST",
                "route_short_name": ref,
                "route_long_name": f"Route {ref}",
                "route_type": 3,
                "osm_rel_id": 1,
                "network": "Xe buýt Thành phố Hồ Chí Minh",
                "is_hcmc_network": True,
                "operator": "Test",
                "from_name": "A",
                "to_name": "B",
                "is_ptv2": True,
                "has_duration": False,
                "opening_hours_raw": "Mo-Su 05:00-21:00",
                "opening_hours_ok": True,
                "shape_length_km": 1.0,
                "in_bbox_length_km": 1.0,
            }
        )
        trips.append(
            {
                "route_id": rid,
                "service_id": "DAILY",
                "trip_id": tid,
                "trip_headsign": "B",
                "direction_id": 0,
                "shape_id": f"s_{rid}",
            }
        )
        for seq, sid in enumerate(sids, start=1):
            stop_times.append(
                {
                    "trip_id": tid,
                    "arrival_time": None,
                    "departure_time": None,
                    "stop_id": sid,
                    "stop_sequence": seq,
                    "timepoint": 0,
                }
            )
        freqs.append(
            {
                "trip_id": tid,
                "start_time": "05:00:00",
                "end_time": "21:00:00",
                "headway_secs": hi,
                "exact_times": 0,
                "interval_raw": f"{lo}-{hi}",
                "interval_min_s": lo,
                "interval_mid_s": mid,
                "interval_max_s": hi,
                "parse_status": "range" if lo != hi else "exact",
            }
        )
    stop_rows = [
        {
            "stop_id": sid,
            "stop_name": sid,
            "stop_lat": lat,
            "stop_lon": lon,
            "in_bbox": True,
            "osm_type": "node",
            "osm_id": idx,
        }
        for idx, (sid, lon, lat) in enumerate(stops, start=1)
    ]
    for name, rows, schema in (
        ("routes.parquet", routes, ROUTES_SCHEMA),
        ("stops.parquet", stop_rows, STOPS_SCHEMA),
        ("trips.parquet", trips, TRIPS_SCHEMA),
        ("stop_times.parquet", stop_times, STOP_TIMES_SCHEMA),
        ("frequencies.parquet", freqs, FREQUENCIES_SCHEMA),
        ("shapes.parquet", shapes, SHAPES_SCHEMA),
    ):
        cols = {f.name: [r.get(f.name) for r in rows] for f in schema}
        pq.write_table(pa.table(cols, schema=schema), gtfs_dir / name)


def test_stitch_rings_and_multipolygon_handle_reversed_segments_and_holes() -> None:
    outer_segs = [
        [(0.0, 0.0), (10.0, 0.0)],
        [(10.0, 10.0), (10.0, 0.0)],  # reversed
        [(10.0, 10.0), (0.0, 10.0)],
        [(0.0, 0.0), (0.0, 10.0)],  # reversed
    ]
    hole_segs = [
        [(2.0, 2.0), (4.0, 2.0), (4.0, 4.0)],
        [(4.0, 4.0), (2.0, 4.0), (2.0, 2.0)],
    ]
    rings = stitch_rings(outer_segs)
    assert len(rings) == 1 and rings[0][0] == rings[0][-1] and len(rings[0]) == 5
    gj = build_multipolygon_geojson(outer_segs, hole_segs)
    assert gj is not None
    parsed = json.loads(gj)
    assert parsed["type"] == "MultiPolygon" and len(parsed["coordinates"][0]) == 2


def test_single_center_stop_matches_exact_circle_area_and_frequency_sensitivity(
    tmp_path: Path,
) -> None:
    """1 km x 1 km ward with 1 center stop (interval 10-20 min):
    - Exact 400 m circle area share = pi * 400^2 / 1000^2 = 0.502655
    - Conservative (max 20 min = 3 bph < 4): 0% frequent coverage
    - Midpoint (mid 15 min = 4 bph >= 4): 50.27% frequent coverage
    """
    cfg = load_config()
    with connect_spatial() as con:
        ward = _square_ward(con, "rel_1", BASE_E, BASE_N, 1000.0)
        center = _utm_to_wgs84(con, BASE_E + 500.0, BASE_N + 500.0)

    gtfs_dir = tmp_path / "gtfs"
    _write_synthetic_gtfs(
        gtfs_dir,
        stops=[("S1", center[0], center[1])],
        routes_intervals=[("08", "osm_1", 600, 900, 1200, ["S1"])],
    )
    out = tmp_path / "out"
    manifest = compute_coverage(gtfs_dir, [ward], cfg, out)
    assert manifest["schema"] == "transitometer.hcmc/1"

    with duckdb.connect() as con:
        row = con.execute(
            f"SELECT area_km2, coverage_any_400m_share, coverage_freq_conservative_share, "
            f"coverage_freq_midpoint_share, active_stops, distinct_routes "
            f"FROM '{(out / 'hcmc_ward_coverage.parquet').as_posix()}'"
        ).fetchone()
    assert row is not None
    area, any_share, cons_share, mid_share, active_stops, distinct_routes = row
    expected_circle = math.pi * 400.0**2 / 1_000_000.0
    assert float(area) == pytest.approx(1.0, rel=1e-3)
    assert float(any_share) == pytest.approx(expected_circle, abs=0.002)
    assert float(cons_share) == 0.0
    assert float(mid_share) == pytest.approx(expected_circle, abs=0.002)
    assert active_stops == 1 and distinct_routes == 1


def test_overlapping_buffers_are_deduplicated_and_cross_border_stop_covers_neighbor(
    tmp_path: Path,
) -> None:
    """Two stops 100 m apart must NOT double-count area; a stop 200 m outside still covers."""
    cfg = load_config()
    with connect_spatial() as con:
        ward_a = _square_ward(con, "rel_10", BASE_E, BASE_N, 1000.0)
        ward_b = _square_ward(con, "rel_20", BASE_E + 1000.0, BASE_N, 1000.0)
        s1 = _utm_to_wgs84(con, BASE_E + 500.0, BASE_N + 500.0)
        s2 = _utm_to_wgs84(con, BASE_E + 600.0, BASE_N + 500.0)  # 100 m from s1
        s_border = _utm_to_wgs84(con, BASE_E + 800.0, BASE_N + 500.0)  # 200 m west of ward_b

    gtfs_dir = tmp_path / "gtfs"
    _write_synthetic_gtfs(
        gtfs_dir,
        stops=[("S1", s1[0], s1[1]), ("S2", s2[0], s2[1]), ("S3", s_border[0], s_border[1])],
        routes_intervals=[("01", "osm_1", 600, 750, 900, ["S1", "S2", "S3"])],
    )
    out = tmp_path / "out"
    compute_coverage(gtfs_dir, [ward_a, ward_b], cfg, out)

    with duckdb.connect() as con:
        rows = {
            r[0]: r[1:]
            for r in con.execute(
                f"SELECT ward_id, coverage_any_400m_share, coverage_freq_conservative_share, "
                f"active_stops FROM '{(out / 'hcmc_ward_coverage.parquet').as_posix()}'"
            ).fetchall()
        }
    # Ward A: 3 overlapping circles inside 1 km^2 -> union < 3 * 0.5026 and <= 1.0
    a_any, a_freq, a_stops = rows["rel_10"]
    assert 0.55 < float(a_any) < 0.85
    assert float(a_freq) == pytest.approx(float(a_any), abs=1e-6)
    assert a_stops == 3

    # Ward B: 0 stops inside, but S3 is 200 m outside -> circular segment spills into Ward B!
    # Exact area of circle (R=400) segment at d=200 from center:
    # R^2 * acos(d/R) - d * sqrt(R^2 - d^2) = 160000 * pi/3 - 200 * 346.41 = 98,269 m^2
    b_any, b_freq, b_stops = rows["rel_20"]
    expected_spill = (400.0**2 * math.acos(0.5) - 200.0 * math.sqrt(400.0**2 - 200.0**2)) / 1e6
    assert b_stops == 0
    assert float(b_any) == pytest.approx(expected_spill, abs=0.002)
    assert float(b_freq) == pytest.approx(expected_spill, abs=0.002)


def test_compute_coverage_is_byte_deterministic(tmp_path: Path) -> None:
    cfg = load_config()
    with connect_spatial() as con:
        ward = _square_ward(con, "rel_1", BASE_E, BASE_N, 1000.0)
        s1 = _utm_to_wgs84(con, BASE_E + 500.0, BASE_N + 500.0)
    gtfs_dir = tmp_path / "gtfs"
    _write_synthetic_gtfs(
        gtfs_dir,
        stops=[("S1", s1[0], s1[1])],
        routes_intervals=[("50", "osm_50", 600, 750, 900, ["S1"])],
    )
    m1 = compute_coverage(gtfs_dir, [ward], cfg, tmp_path / "r1")
    m2 = compute_coverage(gtfs_dir, [ward], cfg, tmp_path / "r2")
    assert m1 == m2


def test_core_wards_config_and_name_matching_audit() -> None:
    cfg = load_config()
    spec = load_core_wards()
    assert spec.resolution == "1685/NQ-UBTVQH15"
    assert len(spec.ordered_names) == 102
    assert len(spec.ward_names) == 102
    assert "Phường Bến Thành" in spec.ward_names
    assert "Xã Hưng Long" in spec.ward_names
    assert "Phường Dĩ An" not in spec.ward_names

    # Synthetic OSM ward doc with one pre-merger HCMC ward and one former Binh Duong ward
    # both located inside the old bbox; name matching must classify only Ben Thanh as core.
    square = [
        {"lat": 10.77, "lon": 106.69},
        {"lat": 10.77, "lon": 106.70},
        {"lat": 10.78, "lon": 106.70},
        {"lat": 10.78, "lon": 106.69},
        {"lat": 10.77, "lon": 106.69},
    ]
    doc = {
        "elements": [
            {
                "type": "relation",
                "id": 1,
                "tags": {"name": "Phường Bến Thành", "admin_level": "6"},
                "members": [{"type": "way", "role": "outer", "geometry": square}],
            },
            {
                "type": "relation",
                "id": 2,
                "tags": {"name": "Phường Dĩ An", "admin_level": "6"},
                "members": [{"type": "way", "role": "outer", "geometry": square}],
            },
        ]
    }
    wards = wards_from_osm(doc, cfg.bbox, core_ward_names=spec.ward_names)
    by_name = {w.ward_name: w.in_core_hcmc for w in wards}
    assert by_name == {"Phường Bến Thành": True, "Phường Dĩ An": False}
    audit = audit_core_ward_matching(wards, spec)
    assert audit["matched"] == 1
    assert audit["expected"] == 102
    assert audit["non_core_osm_count"] == 1
    assert "Xã Hưng Long" in audit["missing_from_osm"]


def test_incomplete_osm_routes_are_flagged_without_affecting_coverage(tmp_path: Path) -> None:
    """Flag routes with < 2 in-bbox stops or > 120 km external detours, not bogus km."""
    cfg = load_config()
    with connect_spatial() as con:
        ward = _square_ward(con, "rel_1", BASE_E, BASE_N, 1000.0)
        s1 = _utm_to_wgs84(con, BASE_E + 400.0, BASE_N + 500.0)
        s2 = _utm_to_wgs84(con, BASE_E + 600.0, BASE_N + 500.0)

    gtfs_dir = tmp_path / "gtfs"
    gtfs_dir.mkdir(parents=True, exist_ok=True)
    routes = [
        {
            "route_id": "r_normal",
            "agency_id": "AG_1",
            "route_short_name": "72-2B",
            "route_long_name": "Normal inter-provincial",
            "route_type": 3,
            "osm_rel_id": 1,
            "network": "Xe buýt Thành phố Hồ Chí Minh",
            "is_hcmc_network": True,
            "operator": "Test",
            "from_name": "A",
            "to_name": "B",
            "is_ptv2": True,
            "has_duration": False,
            "opening_hours_raw": "05:00-21:00",
            "opening_hours_ok": True,
            "shape_length_km": 109.6,
            "in_bbox_length_km": 54.9,
        },
        {
            "route_id": "r_detour",
            "agency_id": "AG_1",
            "route_short_name": "72-1",
            "route_long_name": "External detour > 120 km",
            "route_type": 3,
            "osm_rel_id": 2,
            "network": "Xe buýt Thành phố Hồ Chí Minh",
            "is_hcmc_network": True,
            "operator": "Test",
            "from_name": "A",
            "to_name": "B",
            "is_ptv2": True,
            "has_duration": False,
            "opening_hours_raw": "05:00-21:00",
            "opening_hours_ok": True,
            "shape_length_km": 180.02,
            "in_bbox_length_km": 55.25,
        },
        {
            "route_id": "r_sparse",
            "agency_id": "AG_1",
            "route_short_name": "72-2C",
            "route_long_name": "Sparse stops + external detour",
            "route_type": 3,
            "osm_rel_id": 3,
            "network": "Xe buýt Thành phố Hồ Chí Minh",
            "is_hcmc_network": True,
            "operator": "Test",
            "from_name": "A",
            "to_name": "B",
            "is_ptv2": True,
            "has_duration": False,
            "opening_hours_raw": "05:00-21:00",
            "opening_hours_ok": True,
            "shape_length_km": 137.13,
            "in_bbox_length_km": 52.0,
        },
    ]
    trips = [
        {
            "route_id": r["route_id"],
            "service_id": "DAILY",
            "trip_id": f"t_{r['route_id']}",
            "trip_headsign": "B",
            "direction_id": 0,
            "shape_id": None,
        }
        for r in routes
    ]
    stop_times = [
        {
            "trip_id": "t_r_normal",
            "arrival_time": None,
            "departure_time": None,
            "stop_id": "S1",
            "stop_sequence": 1,
            "timepoint": 0,
        },
        {
            "trip_id": "t_r_normal",
            "arrival_time": None,
            "departure_time": None,
            "stop_id": "S2",
            "stop_sequence": 2,
            "timepoint": 0,
        },
        {
            "trip_id": "t_r_detour",
            "arrival_time": None,
            "departure_time": None,
            "stop_id": "S1",
            "stop_sequence": 1,
            "timepoint": 0,
        },
        {
            "trip_id": "t_r_detour",
            "arrival_time": None,
            "departure_time": None,
            "stop_id": "S2",
            "stop_sequence": 2,
            "timepoint": 0,
        },
        {
            "trip_id": "t_r_sparse",
            "arrival_time": None,
            "departure_time": None,
            "stop_id": "S1",
            "stop_sequence": 1,
            "timepoint": 0,
        },
    ]
    stops = [
        {
            "stop_id": "S1",
            "stop_name": "S1",
            "stop_lat": s1[1],
            "stop_lon": s1[0],
            "in_bbox": True,
            "osm_type": "node",
            "osm_id": 1,
        },
        {
            "stop_id": "S2",
            "stop_name": "S2",
            "stop_lat": s2[1],
            "stop_lon": s2[0],
            "in_bbox": True,
            "osm_type": "node",
            "osm_id": 2,
        },
    ]
    for name, rows_data, schema in (
        ("routes.parquet", routes, ROUTES_SCHEMA),
        ("stops.parquet", stops, STOPS_SCHEMA),
        ("trips.parquet", trips, TRIPS_SCHEMA),
        ("stop_times.parquet", stop_times, STOP_TIMES_SCHEMA),
        ("frequencies.parquet", [], FREQUENCIES_SCHEMA),
        ("shapes.parquet", [], SHAPES_SCHEMA),
    ):
        cols = {f.name: [r.get(f.name) for r in rows_data] for f in schema}
        pq.write_table(pa.table(cols, schema=schema), gtfs_dir / name)

    out = tmp_path / "snap"
    compute_coverage(gtfs_dir, [ward], cfg, out)

    from transitometer.serve import hcmc_views

    with duckdb.connect() as con:
        view = hcmc_views.hcmc_coverage(con, out, scope="core_hcmc", hand_checks_path=None)
    by_ref = {r["route_ref"]: r for r in view["routes"]}
    assert by_ref["72-2B"]["osm_incomplete"] is False
    assert by_ref["72-2B"]["avg_length_km"] == pytest.approx(109.6)
    assert by_ref["72-2B"]["length_display"] == "109.6 km"
    assert by_ref["72-1"]["osm_incomplete"] is True
    assert by_ref["72-1"]["avg_length_km"] is None
    assert by_ref["72-1"]["length_display"] == "Incomplete OSM data"
    assert by_ref["72-2C"]["osm_incomplete"] is True
    assert by_ref["72-2C"]["avg_length_km"] is None
    assert by_ref["72-2C"]["length_display"] == "Incomplete OSM data"
    assert view["wards"][0]["active_stops"] == 2
