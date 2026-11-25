"""Self-hosted map geometry for BR11 (web/public/basemap/hcmc.json): no map tiles, no third party.

Simplifies OSM ward polygons with DuckDB Spatial ST_SimplifyPreserveTopology on EPSG:32648
(35 m tolerance) so ECharts can render an interactive choropleth + bus corridor overlay in
< 600 KB with zero external network calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa

from transitometer.hcmc import HcmcConfig
from transitometer.hcmc.osm_to_gtfs import haversine_km
from transitometer.hcmc.spatial import WardPolygon, connect_spatial
from transitometer.serve import kpis
from transitometer.serve.basemap import simplify

SCHEMA = "transitometer.hcmc-basemap/1"
OUT = kpis.REPO / "web" / "public" / "basemap" / "hcmc.json"
WARD_SIMPLIFY_M = 35.0
ROUTE_EPS_DEG = 0.00045  # ~50 m at HCMC's latitude
MAX_ROUTE_STEP_KM = 0.5  # split disconnected OSM route segments instead of drawing chord lines


def _round_coords(obj: Any, digits: int = 4) -> Any:
    if isinstance(obj, list):
        if len(obj) == 2 and all(isinstance(v, int | float) for v in obj):
            return [round(float(obj[0]), digits), round(float(obj[1]), digits)]
        return [_round_coords(item, digits) for item in obj]
    return obj


def _dedup_ring(ring: list[list[float]]) -> list[list[float]]:
    out: list[list[float]] = []
    for pt in ring:
        if not out or out[-1] != pt:
            out.append(pt)
    if len(out) >= 3 and out[0] != out[-1]:
        out.append(out[0])
    return out


def _clean_geom(geom: dict[str, Any]) -> dict[str, Any]:
    gtype = geom.get("type")
    coords = _round_coords(geom.get("coordinates", []), 4)
    if gtype == "Polygon":
        rings = [_dedup_ring(r) for r in coords]
        rings = [r for r in rings if len(r) >= 4]
        return {"type": "Polygon", "coordinates": rings}
    if gtype == "MultiPolygon":
        polys = []
        for poly in coords:
            rings = [_dedup_ring(r) for r in poly]
            rings = [r for r in rings if len(r) >= 4]
            if rings:
                polys.append(rings)
        return {"type": "MultiPolygon", "coordinates": polys}
    return {"type": gtype, "coordinates": coords}


def _scan(path: Path) -> str:
    return "'" + path.as_posix().replace("'", "''") + "'"


def build(
    wards: list[WardPolygon],
    gtfs_dir: Path,
    hcmc_snapshot_dir: Path,
    cfg: HcmcConfig,
) -> dict[str, Any]:
    """Produce simplified ward GeoJSON + bus route lines + stop points for ECharts."""
    wards_arrow = pa.table(
        {
            "ward_id": [w.ward_id for w in wards],
            "ward_name": [w.ward_name for w in wards],
            "in_core_hcmc": [w.in_core_hcmc for w in wards],
            "geojson": [w.geojson for w in wards],
        }
    )
    features: list[dict[str, Any]] = []
    with connect_spatial() as con:
        con.register("raw_wards", wards_arrow)
        rows = con.execute(
            f"""
            WITH utm AS (
                SELECT
                    ward_id,
                    ward_name,
                    in_core_hcmc,
                    ST_SimplifyPreserveTopology(
                        ST_MakeValid(
                            ST_Transform(
                                ST_MakeValid(ST_GeomFromGeoJSON(geojson)),
                                'EPSG:4326',
                                '{cfg.crs}',
                                always_xy := true
                            )
                        ),
                        {WARD_SIMPLIFY_M}
                    ) AS simple_utm
                FROM raw_wards
            )
            SELECT
                ward_id,
                ward_name,
                in_core_hcmc,
                ST_AsGeoJSON(
                    ST_Transform(simple_utm, '{cfg.crs}', 'EPSG:4326', always_xy := true)
                ) AS gj
            FROM utm
            WHERE simple_utm IS NOT NULL AND NOT ST_IsEmpty(simple_utm)
            ORDER BY ward_id
            """
        ).fetchall()
    for ward_id, ward_name, in_core, gj in rows:
        geom = _clean_geom(json.loads(gj))
        if not geom.get("coordinates"):
            continue
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "name": str(ward_id),
                    "ward_name": str(ward_name),
                    "in_core_hcmc": bool(in_core),
                },
                "geometry": geom,
            }
        )

    # Simplified primary HCMC bus route corridors (one representative direction per route_ref)
    routes_p = _scan(gtfs_dir / "routes.parquet")
    trips_p = _scan(gtfs_dir / "trips.parquet")
    shapes_p = _scan(gtfs_dir / "shapes.parquet")
    stops_p = _scan(hcmc_snapshot_dir / "hcmc_stops.parquet")

    with duckdb.connect() as con:
        shape_rows = con.execute(
            f"""
            WITH picked AS (
                SELECT coalesce(nullif(r.route_short_name, ''), r.route_id) AS ref,
                       min(nullif(t.shape_id, '')) AS shape_id
                FROM read_parquet({routes_p}) r
                JOIN read_parquet({trips_p}) t USING (route_id)
                WHERE r.is_hcmc_network = true AND nullif(t.shape_id, '') IS NOT NULL
                GROUP BY 1
            )
            SELECT p.shape_id,
                   list(struct_pack(x := s.shape_pt_lon::DOUBLE, y := s.shape_pt_lat::DOUBLE)
                        ORDER BY s.shape_pt_sequence) AS pts
            FROM picked p
            JOIN read_parquet({shapes_p}) s USING (shape_id)
            GROUP BY p.shape_id
            ORDER BY p.shape_id
            """
        ).fetchall()
        stop_rows = con.execute(
            f"""
            SELECT round(stop_lon, 4), round(stop_lat, 4), route_count, is_frequent_conservative
            FROM read_parquet({stops_p})
            ORDER BY stop_id
            """
        ).fetchall()

    pad = 0.02
    lon_lo, lon_hi = cfg.bbox.west - pad, cfg.bbox.east + pad
    lat_lo, lat_hi = cfg.bbox.south - pad, cfg.bbox.north + pad

    route_lines: list[list[list[float]]] = []
    for _, pts in shape_rows:
        raw_pts = [(float(p["x"]), float(p["y"])) for p in pts]
        segments: list[list[tuple[float, float]]] = []
        cur: list[tuple[float, float]] = []
        for pt in raw_pts:
            in_frame = lon_lo <= pt[0] <= lon_hi and lat_lo <= pt[1] <= lat_hi
            if not in_frame:
                if len(cur) >= 2:
                    segments.append(cur)
                cur = []
                continue
            if cur and haversine_km(cur[-1][1], cur[-1][0], pt[1], pt[0]) > MAX_ROUTE_STEP_KM:
                if len(cur) >= 2:
                    segments.append(cur)
                cur = [pt]
            else:
                cur.append(pt)
        if len(cur) >= 2:
            segments.append(cur)
        for seg in segments:
            simp = simplify(seg, ROUTE_EPS_DEG)
            rounded: list[list[float]] = []
            for x, y in simp:
                pt_r = [round(x, 4), round(y, 4)]
                if not rounded or rounded[-1] != pt_r:
                    rounded.append(pt_r)
            if len(rounded) >= 2:
                route_lines.append(rounded)

    stops_compact = [
        [float(lon), float(lat), int(rc), bool(freq)] for lon, lat, rc, freq in stop_rows
    ]

    return {
        "schema": SCHEMA,
        "source": f"{cfg.city} OSM wards & bus routes ({cfg.attribution})",
        "core_frame": {
            "lon": [cfg.bbox.west, cfg.bbox.east],
            "lat": [cfg.bbox.south, cfg.bbox.north],
        },
        "wards": {"type": "FeatureCollection", "features": features},
        "routes": route_lines,
        "stops": stops_compact,
    }


def write(basemap: dict[str, Any], out: Path = OUT) -> dict[str, int]:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(basemap, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {
        "wards": len(basemap["wards"]["features"]),
        "routes": len(basemap["routes"]),
        "stops": len(basemap["stops"]),
        "bytes": out.stat().st_size,
    }
