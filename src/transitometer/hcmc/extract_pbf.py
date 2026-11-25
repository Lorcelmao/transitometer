"""Extract HCMC bus routes and 168 municipal ward boundaries from Geofabrik vietnam-latest.osm.pbf.

Uses DuckDB Spatial's native ST_ReadOSM() table function in 3 filtered scans (relations -> ways ->
nodes) so extraction completes offline in ~15 seconds without Overpass rate limits or timeouts,
producing the exact Overpass-compatible JSON documents consumed by osm_to_gtfs.py and spatial.py.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pyarrow as pa

from transitometer.hcmc import BBox, HcmcConfig
from transitometer.hcmc.spatial import connect_spatial


def _scan_pbf(path: Path) -> str:
    return "'" + path.as_posix().replace("'", "''") + "'"


def _to_str_tags(raw: Any) -> dict[str, str]:
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items() if v is not None}
    return {}


def extract_from_pbf(
    pbf_path: Path,
    cfg: HcmcConfig,
    bus_out: Path,
    wards_out: Path,
    log: Callable[[str], None] = lambda msg: print(msg, flush=True),
) -> dict[str, Any]:
    """Read vietnam-latest.osm.pbf with DuckDB ST_ReadOSM and write bus + ward JSON extracts."""
    pbf = _scan_pbf(pbf_path)
    bbox: BBox = cfg.bbox

    with connect_spatial() as con:
        log(f"scanning relations from {pbf_path.name} via DuckDB ST_ReadOSM ...")
        # Keep all relations before SEMI JOIN on subarea_ids so a subarea mistagged without
        # boundary=administrative (e.g. relation/7462678 Xa Hung Long tagged type=site) is not lost.
        con.execute(
            f"""
            CREATE TEMP TABLE rels AS
            SELECT id, tags, refs, ref_roles, ref_types
            FROM ST_ReadOSM({pbf})
            WHERE kind = 'relation'
            """
        )

        # Resolve the exact 168 subarea ward relation IDs from relation/1973756.
        city_row = con.execute(
            f"SELECT id, tags, refs, ref_roles, ref_types FROM rels "
            f"WHERE id = {cfg.osm_city_relation_id}"
        ).fetchone()
        if city_row is None:
            raise ValueError(
                f"City relation {cfg.osm_city_relation_id} not found in {pbf_path.name}"
            )
        city_tags = _to_str_tags(city_row[1])
        subarea_ids = sorted(
            int(ref)
            for ref, role, rtype in zip(
                city_row[2] or [], city_row[3] or [], city_row[4] or [], strict=False
            )
            if str(rtype) == "relation" and str(role) == "subarea"
        )
        log(
            f"found {len(subarea_ids)} subarea ward relations "
            f"inside relation/{cfg.osm_city_relation_id}"
        )

        con.register("subarea_ids", pa.table({"id": pa.array(subarea_ids, type=pa.int64())}))

        ward_rows = con.execute(
            """
            SELECT r.id, r.tags, r.refs, r.ref_roles, r.ref_types
            FROM rels r
            SEMI JOIN subarea_ids s USING (id)
            ORDER BY r.id
            """
        ).fetchall()

        bus_rows = con.execute(
            """
            SELECT id, tags, refs, ref_roles, ref_types
            FROM rels
            WHERE tags['type'] = 'route' AND tags['route'] = 'bus'
            ORDER BY id
            """
        ).fetchall()
        log(
            f"loaded {len(ward_rows)} ward relations and {len(bus_rows)} candidate VN bus relations"
        )

        # Collect all member way IDs and direct node IDs needed by wards + candidate bus routes.
        way_ids: set[int] = set()
        direct_node_ids: set[int] = set()
        for row in (*ward_rows, *bus_rows):
            for ref, rtype in zip(row[2] or [], row[4] or [], strict=False):
                rt = str(rtype)
                if rt == "way":
                    way_ids.add(int(ref))
                elif rt == "node":
                    direct_node_ids.add(int(ref))

        log(f"resolving {len(way_ids):,} member ways ...")
        con.register("need_ways", pa.table({"id": pa.array(sorted(way_ids), type=pa.int64())}))
        ways_map: dict[int, tuple[dict[str, str], list[int]]] = {}
        all_node_ids: set[int] = set(direct_node_ids)
        for wid, wtags, wrefs in con.execute(
            f"""
            SELECT w.id, w.tags, w.refs
            FROM ST_ReadOSM({pbf}) w
            SEMI JOIN need_ways n ON w.kind = 'way' AND w.id = n.id
            """
        ).fetchall():
            ref_list = [int(x) for x in (wrefs or [])]
            ways_map[int(wid)] = (_to_str_tags(wtags), ref_list)
            all_node_ids.update(ref_list)

        log(f"resolving {len(all_node_ids):,} referenced nodes ...")
        con.register(
            "need_nodes", pa.table({"id": pa.array(sorted(all_node_ids), type=pa.int64())})
        )
        nodes_map: dict[int, tuple[float, float, dict[str, str]]] = {}
        for nid, lat, lon, ntags in con.execute(
            f"""
            SELECT nd.id, nd.lat, nd.lon, nd.tags
            FROM ST_ReadOSM({pbf}) nd
            SEMI JOIN need_nodes n ON nd.kind = 'node' AND nd.id = n.id
            WHERE nd.lat IS NOT NULL AND nd.lon IS NOT NULL
            """
        ).fetchall():
            nodes_map[int(nid)] = (float(lat), float(lon), _to_str_tags(ntags))

    def _way_geom(wid: int) -> list[dict[str, float]]:
        entry = ways_map.get(wid)
        if entry is None:
            return []
        _, nrefs = entry
        pts: list[dict[str, float]] = []
        for nid in nrefs:
            nd = nodes_map.get(nid)
            if nd is not None:
                pts.append({"lat": round(nd[0], 6), "lon": round(nd[1], 6)})
        return pts

    # Build Overpass-compatible bus_routes JSON filtered to relations touching the core HCMC bbox.
    bus_elements: list[dict[str, Any]] = []
    extra_tag_nodes: dict[int, dict[str, Any]] = {}
    extra_tag_ways: dict[int, dict[str, Any]] = {}
    kept_bus = 0

    for rid, rtags, rrefs, rroles, rtypes in bus_rows:
        members_out: list[dict[str, Any]] = []
        touches_bbox = False
        for ref, role, rtype in zip(rrefs or [], rroles or [], rtypes or [], strict=False):
            ref_id = int(ref)
            role_s = str(role or "")
            rt = str(rtype)
            if rt == "node":
                nd = nodes_map.get(ref_id)
                if nd is None:
                    continue
                lat, lon, ntags = nd
                if bbox.contains(lat, lon):
                    touches_bbox = True
                members_out.append(
                    {
                        "type": "node",
                        "ref": ref_id,
                        "role": role_s,
                        "lat": round(lat, 6),
                        "lon": round(lon, 6),
                    }
                )
                if ntags and ref_id not in extra_tag_nodes:
                    extra_tag_nodes[ref_id] = {"type": "node", "id": ref_id, "tags": ntags}
            elif rt == "way":
                geom = _way_geom(ref_id)
                if not geom:
                    continue
                if not touches_bbox and any(bbox.contains(p["lat"], p["lon"]) for p in geom):
                    touches_bbox = True
                members_out.append({"type": "way", "ref": ref_id, "role": role_s, "geometry": geom})
                w_entry = ways_map.get(ref_id)
                if w_entry and w_entry[0] and role_s.startswith("platform"):
                    extra_tag_ways[ref_id] = {"type": "way", "id": ref_id, "tags": w_entry[0]}
        if not touches_bbox:
            continue
        kept_bus += 1
        bus_elements.append(
            {
                "type": "relation",
                "id": int(rid),
                "tags": _to_str_tags(rtags),
                "members": members_out,
            }
        )

    bus_elements.extend(extra_tag_nodes[k] for k in sorted(extra_tag_nodes))
    bus_elements.extend(extra_tag_ways[k] for k in sorted(extra_tag_ways))
    bus_elements.sort(key=lambda e: (str(e["type"]), int(e["id"])))

    bus_payload = {
        "schema": "transitometer.osm-bus/1",
        "source": f"geofabrik:{pbf_path.name}",
        "bbox": bbox.overpass(),
        "elements": bus_elements,
    }
    bus_out.parent.mkdir(parents=True, exist_ok=True)
    bus_out.write_text(
        json.dumps(bus_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    # Build Overpass-compatible admin_wards JSON for all 168 subarea wards of relation/1973756.
    ward_elements: list[dict[str, Any]] = []
    for rid, rtags, rrefs, rroles, rtypes in ward_rows:
        members_out = []
        for ref, role, rtype in zip(rrefs or [], rroles or [], rtypes or [], strict=False):
            if str(rtype) != "way":
                continue
            geom = _way_geom(int(ref))
            if len(geom) >= 2:
                members_out.append(
                    {
                        "type": "way",
                        "ref": int(ref),
                        "role": str(role or ""),
                        "geometry": geom,
                    }
                )
        ward_elements.append(
            {
                "type": "relation",
                "id": int(rid),
                "tags": _to_str_tags(rtags),
                "members": members_out,
            }
        )

    ward_payload = {
        "schema": "transitometer.osm-wards/1",
        "source": f"geofabrik:{pbf_path.name}",
        "city_relation_id": cfg.osm_city_relation_id,
        "city_tags": city_tags,
        "subarea_count": len(subarea_ids),
        "elements": ward_elements,
    }
    wards_out.parent.mkdir(parents=True, exist_ok=True)
    wards_out.write_text(
        json.dumps(ward_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    log(
        f"extracted {kept_bus} HCMC bus relations ({bus_out.stat().st_size / 1e6:.2f} MB) "
        f"and {len(ward_elements)}/{len(subarea_ids)} ward relations "
        f"({wards_out.stat().st_size / 1e6:.2f} MB)"
    )
    return {
        "bus_relations": kept_bus,
        "bus_bytes": bus_out.stat().st_size,
        "wards": len(ward_elements),
        "expected_subareas": len(subarea_ids),
        "wards_bytes": wards_out.stat().st_size,
    }
