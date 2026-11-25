"""Unit tests for BR11 shared serving views (serve/hcmc_views.py) and basemap builder."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from transitometer.hcmc import load_config
from transitometer.hcmc.osm_to_gtfs import (
    FREQUENCIES_SCHEMA,
    ROUTES_SCHEMA,
    SHAPES_SCHEMA,
    STOP_TIMES_SCHEMA,
    STOPS_SCHEMA,
    TRIPS_SCHEMA,
)
from transitometer.hcmc.spatial import WardPolygon, compute_coverage, connect_spatial
from transitometer.serve import hcmc_basemap, hcmc_views

BASE_E = 685_000.0
BASE_N = 1_191_000.0


def _utm_to_wgs84(con: duckdb.DuckDBPyConnection, x: float, y: float) -> tuple[float, float]:
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
    in_core: bool,
) -> WardPolygon:
    pts = [
        list(_utm_to_wgs84(con, x, y))
        for x, y in (
            (x0, y0),
            (x0 + size_m, y0),
            (x0 + size_m, y0 + size_m),
            (x0, y0 + size_m),
            (x0, y0),
        )
    ]
    gj = json.dumps({"type": "MultiPolygon", "coordinates": [[pts]]}, separators=(",", ":"))
    return WardPolygon(
        ward_id=ward_id,
        osm_rel_id=int(ward_id.split("_")[-1]),
        ward_name=f"Ward {ward_id}",
        name_en="",
        admin_level="6",
        geojson=gj,
        in_core_hcmc=in_core,
    )


def _write_minimal_gtfs(gtfs_dir: Path, stop_lon: float, stop_lat: float) -> None:
    gtfs_dir.mkdir(parents=True, exist_ok=True)
    tables: list[tuple[str, list[dict[str, object]], pa.Schema]] = [
        (
            "routes.parquet",
            [
                {
                    "route_id": "osm_1",
                    "agency_id": "AG_1",
                    "route_short_name": "08",
                    "route_long_name": "Route 08",
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
            ],
            ROUTES_SCHEMA,
        ),
        (
            "stops.parquet",
            [
                {
                    "stop_id": "S1",
                    "stop_name": "Stop 1",
                    "stop_lat": stop_lat,
                    "stop_lon": stop_lon,
                    "in_bbox": True,
                    "osm_type": "node",
                    "osm_id": 1,
                }
            ],
            STOPS_SCHEMA,
        ),
        (
            "trips.parquet",
            [
                {
                    "route_id": "osm_1",
                    "service_id": "DAILY",
                    "trip_id": "t_1",
                    "trip_headsign": "B",
                    "direction_id": 0,
                    "shape_id": "sh_1",
                }
            ],
            TRIPS_SCHEMA,
        ),
        (
            "stop_times.parquet",
            [
                {
                    "trip_id": "t_1",
                    "arrival_time": None,
                    "departure_time": None,
                    "stop_id": "S1",
                    "stop_sequence": 1,
                    "timepoint": 0,
                }
            ],
            STOP_TIMES_SCHEMA,
        ),
        (
            "frequencies.parquet",
            [
                {
                    "trip_id": "t_1",
                    "start_time": "05:00:00",
                    "end_time": "21:00:00",
                    "headway_secs": 900,
                    "exact_times": 0,
                    "interval_raw": "00:10-00:15",
                    "interval_min_s": 600,
                    "interval_mid_s": 750,
                    "interval_max_s": 900,
                    "parse_status": "range",
                }
            ],
            FREQUENCIES_SCHEMA,
        ),
        ("shapes.parquet", [], SHAPES_SCHEMA),
    ]
    for name, rows, schema in tables:
        cols = {f.name: [r.get(f.name) for r in rows] for f in schema}
        pq.write_table(pa.table(cols, schema=schema), gtfs_dir / name)


def test_hcmc_view_formats_figures_and_separates_scopes(tmp_path: Path) -> None:
    cfg = load_config()
    with connect_spatial() as con:
        w_core = _square_ward(con, "rel_1", BASE_E, BASE_N, 1000.0, in_core=True)
        w_outer = _square_ward(con, "rel_2", BASE_E + 20_000.0, BASE_N, 2000.0, in_core=False)
        s1 = _utm_to_wgs84(con, BASE_E + 500.0, BASE_N + 500.0)

    gtfs_dir = tmp_path / "gtfs"
    _write_minimal_gtfs(gtfs_dir, s1[0], s1[1])
    snap = tmp_path / "hcmc_snap"
    compute_coverage(gtfs_dir, [w_core, w_outer], cfg, snap)

    with duckdb.connect() as con:
        core_view = hcmc_views.hcmc_coverage(con, snap, scope="core_hcmc", hand_checks_path=None)
        all_view = hcmc_views.hcmc_coverage(
            con, snap, scope="merged_city_all", hand_checks_path=None
        )

    assert core_view["available"] is True
    assert len(core_view["wards"]) == 1
    assert len(all_view["wards"]) == 2
    assert [f["key"] for f in core_view["figures"]] == [
        "coverage_any",
        "coverage_freq",
        "routes_mapped",
        "interval_coverage",
    ]
    core_share = core_view["figures"][0]["value"]
    all_share = all_view["figures"][0]["value"]
    assert core_share == pytest.approx(0.5026, abs=0.005)
    assert all_share == pytest.approx(0.5026 / 5.0, abs=0.005)

    bm = hcmc_basemap.build([w_core, w_outer], gtfs_dir, snap, cfg)
    assert bm["schema"] == hcmc_basemap.SCHEMA
    assert len(bm["wards"]["features"]) == 2
    assert len(bm["stops"]) == 1
    out_bm = tmp_path / "hcmc.json"
    written = hcmc_basemap.write(bm, out_bm)
    assert written["wards"] == 2 and out_bm.exists()


def test_hcmc_view_rejects_unknown_scope(tmp_path: Path) -> None:
    with duckdb.connect() as con, pytest.raises(ValueError, match="Unknown HCMC scope"):
        hcmc_views.hcmc_coverage(con, tmp_path, scope="invalid_scope")
