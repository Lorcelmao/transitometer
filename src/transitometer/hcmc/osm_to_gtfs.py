"""Convert OSM HCMC bus route relations into a frequency-based GTFS archive + Parquet tables.

Design choices driven by measured OSM HCMC data (2026-11-24):
- ~93% of route relations carry `interval` as a peak/off-peak range (e.g. '00:10-00:20').
  We parse both ranges and single values into (min_s, mid_s, max_s) and place the conservative
  upper bound `max_s` into GTFS frequencies.txt (`exact_times=0`).
- Only ~1.1% of route relations carry `duration`, so `stop_times.txt` preserves exact stop order
  without fabricating synthetic arrival timestamps.
- Route ways are stitched into ordered shapes.txt polylines with cumulative Haversine distance.
"""

from __future__ import annotations

import csv
import io
import math
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from transitometer.hcmc import BBox, HcmcConfig

STOP_ROLES = frozenset(
    {
        "stop",
        "stop_entry_only",
        "stop_exit_only",
        "platform",
        "platform_entry_only",
        "platform_exit_only",
    }
)
MIN_INTERVAL_S = 60
MAX_INTERVAL_S = 14_400  # 4 hours

_HMS = re.compile(r"^(?P<h>\d{1,2}):(?P<m>\d{2})(?::(?P<s>\d{2}))?$")
_PLAIN_MIN = re.compile(r"^(?P<m>\d+(?:\.\d+)?)\s*(?:min|mins|m|phút)?$", re.IGNORECASE)
_ISO_PT = re.compile(r"^PT(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+)S)?$", re.IGNORECASE)
_TIME_RANGE = re.compile(r"(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})")


@dataclass(frozen=True)
class IntervalSpec:
    raw: str | None
    min_s: int | None
    mid_s: int | None
    max_s: int | None
    status: str  # "range" | "exact" | "missing" | "unparsed" | "out_of_range"


def _parse_single_duration(token: str) -> int | None:
    text = token.strip()
    if not text:
        return None
    m = _HMS.match(text)
    if m:
        h, mins = int(m.group("h")), int(m.group("m"))
        secs = int(m.group("s") or 0)
        return h * 3600 + mins * 60 + secs
    m = _ISO_PT.match(text)
    if m and any(m.group(k) for k in ("h", "m", "s")):
        return int(m.group("h") or 0) * 3600 + int(m.group("m") or 0) * 60 + int(m.group("s") or 0)
    m = _PLAIN_MIN.match(text)
    if m:
        return round(float(m.group("m")) * 60)
    return None


def parse_interval(raw: str | None) -> IntervalSpec:
    """Parse OSM `interval` tag ('00:10-00:20', '01:00', '15', 'PT15M') into seconds."""
    if raw is None or not raw.strip():
        return IntervalSpec(raw, None, None, None, "missing")
    cleaned = raw.strip().replace("–", "-").replace("—", "-")
    # Handle semicolon-delimited alternatives by taking the overall min..max span.
    parts = [p.strip() for p in re.split(r"[;,]", cleaned) if p.strip()]
    values: list[int] = []
    saw_range = False
    for part in parts:
        # Split a single range 'a-b' (avoiding negative numbers)
        if "-" in part:
            halves = [h.strip() for h in part.split("-", 1)]
            a, b = _parse_single_duration(halves[0]), _parse_single_duration(halves[1])
            if a is not None and b is not None:
                values.extend((a, b))
                saw_range = True
                continue
        val = _parse_single_duration(part)
        if val is not None:
            values.append(val)
    if not values:
        return IntervalSpec(raw, None, None, None, "unparsed")
    lo, hi = min(values), max(values)
    if lo < MIN_INTERVAL_S or hi > MAX_INTERVAL_S:
        return IntervalSpec(raw, None, None, None, "out_of_range")
    mid = round((lo + hi) / 2)
    status = "range" if (saw_range or lo != hi) else "exact"
    return IntervalSpec(raw, lo, mid, hi, status)


def parse_opening_hours(raw: str | None) -> tuple[str, str, bool]:
    """Extract (start_time, end_time, parsed_ok) in HH:MM:SS from OSM opening_hours."""
    if not raw or not raw.strip():
        return "05:00:00", "21:00:00", False
    if "24/7" in raw:
        return "00:00:00", "24:00:00", True
    match = _TIME_RANGE.search(raw)
    if not match:
        return "05:00:00", "21:00:00", False
    start, end = match.group(1), match.group(2)
    sh, sm = (int(x) for x in start.split(":"))
    eh, em = (int(x) for x in end.split(":"))
    if not (0 <= sh <= 23 and 0 <= sm <= 59 and 0 <= eh <= 29 and 0 <= em <= 59):
        return "05:00:00", "21:00:00", False
    if (eh, em) <= (sh, sm):
        eh += 24
    return f"{sh:02d}:{sm:02d}:00", f"{eh:02d}:{em:02d}:00", True


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2.0 * r * math.asin(min(1.0, math.sqrt(a)))


def sum_way_lengths_km(ways: list[list[tuple[float, float]]]) -> float:
    """Sum lengths of individual OSM way geometries without counting inter-way gaps."""
    total = 0.0
    for way in ways:
        for a, b in zip(way, way[1:], strict=False):
            total += haversine_km(a[0], a[1], b[0], b[1])
    return total


def sum_in_bbox_way_lengths_km(ways: list[list[tuple[float, float]]], bbox: BBox) -> float:
    """Sum lengths of OSM way segments whose midpoint falls inside the study bounding box."""
    total = 0.0
    for way in ways:
        for a, b in zip(way, way[1:], strict=False):
            mid_lat = 0.5 * (a[0] + b[0])
            mid_lon = 0.5 * (a[1] + b[1])
            if bbox.contains(mid_lat, mid_lon):
                total += haversine_km(a[0], a[1], b[0], b[1])
    return total


def stitch_way_chain(ways: list[list[tuple[float, float]]]) -> list[tuple[float, float]]:
    """Orient and stitch route ways end-to-end so shape_pt_sequence follows the corridor."""
    cleaned = [list(w) for w in ways if len(w) >= 2]
    if not cleaned:
        return []
    if len(cleaned) == 1:
        return cleaned[0]

    # Merge any touching ways into maximal connected chains so an out-of-order OSM member
    # sharing an endpoint with the corridor is stitched back into place.
    chains: list[list[tuple[float, float]]] = [cleaned[0]]
    for way in cleaned[1:]:
        attached = False
        for ch in reversed(chains):
            if way[0] == ch[-1]:
                ch.extend(way[1:])
                attached = True
            elif way[-1] == ch[-1]:
                ch.extend(reversed(way[:-1]))
                attached = True
            elif way[-1] == ch[0]:
                ch[0:0] = way[:-1]
                attached = True
            elif way[0] == ch[0]:
                ch[0:0] = list(reversed(way[1:]))
                attached = True
            if attached:
                break
        if not attached:
            chains.append(way)

    # Iteratively join separate chains whose endpoints now touch.
    merged = True
    while merged and len(chains) > 1:
        merged = False
        i = 0
        while i < len(chains):
            j = i + 1
            while j < len(chains):
                a, b = chains[i], chains[j]
                if b[0] == a[-1]:
                    a.extend(b[1:])
                elif b[-1] == a[-1]:
                    a.extend(reversed(b[:-1]))
                elif b[-1] == a[0]:
                    a[0:0] = b[:-1]
                elif b[0] == a[0]:
                    a[0:0] = list(reversed(b[1:]))
                else:
                    j += 1
                    continue
                chains.pop(j)
                merged = True
            i += 1

    out: list[tuple[float, float]] = list(chains[0])
    for seg in chains[1:]:
        pts = list(seg)
        d_head = haversine_km(out[-1][0], out[-1][1], pts[0][0], pts[0][1])
        d_tail = haversine_km(out[-1][0], out[-1][1], pts[-1][0], pts[-1][1])
        if d_tail < d_head:
            pts.reverse()
        out.extend(pts)
    return out


def _member_coords(member: dict[str, Any]) -> tuple[float, float] | None:
    """Return (lat, lon) for a node member or centroid of a way platform member."""
    if "lat" in member and "lon" in member:
        return float(member["lat"]), float(member["lon"])
    geom = member.get("geometry")
    if isinstance(geom, list) and geom:
        lats = [float(p["lat"]) for p in geom if "lat" in p and "lon" in p]
        lons = [float(p["lon"]) for p in geom if "lat" in p and "lon" in p]
        if lats and lons:
            return sum(lats) / len(lats), sum(lons) / len(lons)
    return None


def _write_table(rows: list[dict[str, Any]], schema: pa.Schema, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols: dict[str, list[Any]] = {f.name: [r.get(f.name) for r in rows] for f in schema}
    table = pa.table(cols, schema=schema)
    pq.write_table(table, path)


def _csv_bytes(rows: list[dict[str, Any]], fieldnames: list[str]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in fieldnames})
    return buf.getvalue().encode("utf-8")


ROUTES_SCHEMA = pa.schema(
    [
        ("route_id", pa.string()),
        ("agency_id", pa.string()),
        ("route_short_name", pa.string()),
        ("route_long_name", pa.string()),
        ("route_type", pa.int32()),
        ("osm_rel_id", pa.int64()),
        ("network", pa.string()),
        ("is_hcmc_network", pa.bool_()),
        ("operator", pa.string()),
        ("from_name", pa.string()),
        ("to_name", pa.string()),
        ("is_ptv2", pa.bool_()),
        ("has_duration", pa.bool_()),
        ("opening_hours_raw", pa.string()),
        ("opening_hours_ok", pa.bool_()),
        ("shape_length_km", pa.float64()),
        ("in_bbox_length_km", pa.float64()),
    ]
)

STOPS_SCHEMA = pa.schema(
    [
        ("stop_id", pa.string()),
        ("stop_name", pa.string()),
        ("stop_lat", pa.float64()),
        ("stop_lon", pa.float64()),
        ("in_bbox", pa.bool_()),
        ("osm_type", pa.string()),
        ("osm_id", pa.int64()),
    ]
)

TRIPS_SCHEMA = pa.schema(
    [
        ("route_id", pa.string()),
        ("service_id", pa.string()),
        ("trip_id", pa.string()),
        ("trip_headsign", pa.string()),
        ("direction_id", pa.int32()),
        ("shape_id", pa.string()),
    ]
)

STOP_TIMES_SCHEMA = pa.schema(
    [
        ("trip_id", pa.string()),
        ("arrival_time", pa.string()),
        ("departure_time", pa.string()),
        ("stop_id", pa.string()),
        ("stop_sequence", pa.int32()),
        ("timepoint", pa.int32()),
    ]
)

FREQUENCIES_SCHEMA = pa.schema(
    [
        ("trip_id", pa.string()),
        ("start_time", pa.string()),
        ("end_time", pa.string()),
        ("headway_secs", pa.int32()),
        ("exact_times", pa.int32()),
        ("interval_raw", pa.string()),
        ("interval_min_s", pa.int32()),
        ("interval_mid_s", pa.int32()),
        ("interval_max_s", pa.int32()),
        ("parse_status", pa.string()),
    ]
)

SHAPES_SCHEMA = pa.schema(
    [
        ("shape_id", pa.string()),
        ("shape_pt_lat", pa.float64()),
        ("shape_pt_lon", pa.float64()),
        ("shape_pt_sequence", pa.int32()),
        ("shape_dist_traveled", pa.float64()),
    ]
)


def convert_osm_to_gtfs(
    osm_bus_doc: dict[str, Any],
    cfg: HcmcConfig,
    out_dir: Path,
    feed_version: str = "2026-11-24",
) -> dict[str, Any]:
    """Build GTFS Parquet tables and gtfs_hcmc.zip from an Overpass bus JSON document."""
    elements: list[dict[str, Any]] = osm_bus_doc.get("elements", [])
    tag_lookup: dict[tuple[str, int], dict[str, str]] = {}
    relations: list[dict[str, Any]] = []
    for elem in elements:
        etype = str(elem.get("type", ""))
        eid = int(elem.get("id", 0))
        if etype == "relation":
            relations.append(elem)
        else:
            tags = elem.get("tags")
            if isinstance(tags, dict):
                tag_lookup[(etype, eid)] = {str(k): str(v) for k, v in tags.items()}
    relations.sort(key=lambda r: int(r["id"]))

    bbox: BBox = cfg.bbox
    agencies: dict[str, str] = {}
    routes_rows: list[dict[str, Any]] = []
    trips_rows: list[dict[str, Any]] = []
    stop_times_rows: list[dict[str, Any]] = []
    freq_rows: list[dict[str, Any]] = []
    shapes_rows: list[dict[str, Any]] = []
    stops_by_id: dict[str, dict[str, Any]] = {}

    # Track direction_id deterministically per (network, ref)
    ref_dir_counter: dict[tuple[str, str], int] = {}

    for rel in relations:
        rel_id = int(rel["id"])
        raw_tags = rel.get("tags") or {}
        rel_tags: dict[str, str] = {str(k): str(v) for k, v in raw_tags.items()}
        ref = rel_tags.get("ref", "").strip()
        name = rel_tags.get("name", f"OSM route {rel_id}").strip()
        network = rel_tags.get("network", "").strip()
        operator = rel_tags.get("operator", "Unknown operator").strip()
        # Deterministic agency_id without Python hash randomisation:
        agency_id = "AG_" + re.sub(r"[^a-z0-9]+", "_", operator.lower()).strip("_")[:32] or "AG_0"
        agencies[agency_id] = operator

        is_hcmc = network == cfg.primary_network
        is_ptv2 = rel_tags.get("public_transport:version", "").strip() == "2"
        has_duration = bool(rel_tags.get("duration", "").strip())
        oh_raw = rel_tags.get("opening_hours")
        start_time, end_time, oh_ok = parse_opening_hours(oh_raw)
        interval_raw = rel_tags.get("interval") or rel_tags.get("interval:conditional")
        interval = parse_interval(interval_raw)

        route_id = f"osm_{rel_id}"
        trip_id = f"trip_{rel_id}"
        shape_id = f"shape_{rel_id}"
        dir_key = (network, ref or route_id)
        direction_id = ref_dir_counter.get(dir_key, 0)
        ref_dir_counter[dir_key] = direction_id + 1

        # Extract ordered stop/platform members and route ways
        members: list[dict[str, Any]] = rel.get("members", [])
        seen_stop_in_trip: set[str] = set()
        seq = 0
        route_ways: list[list[tuple[float, float]]] = []
        for m in members:
            role = str(m.get("role", "")).strip()
            mtype = str(m.get("type", ""))
            mref = int(m.get("ref", 0))
            if role in STOP_ROLES:
                coords = _member_coords(m)
                if coords is None:
                    continue
                lat, lon = coords
                stop_id = f"{mtype}_{mref}"
                if stop_id not in stops_by_id:
                    mtags = tag_lookup.get((mtype, mref), {})
                    sname = mtags.get("name") or mtags.get("name:vi") or ""
                    stops_by_id[stop_id] = {
                        "stop_id": stop_id,
                        "stop_name": sname.strip(),
                        "stop_lat": round(lat, 6),
                        "stop_lon": round(lon, 6),
                        "in_bbox": bbox.contains(lat, lon),
                        "osm_type": mtype,
                        "osm_id": mref,
                    }
                # PTv2 relations often list both stop_position and platform consecutively;
                # deduplicate exact same stop_id within a single trip.
                if stop_id not in seen_stop_in_trip:
                    seen_stop_in_trip.add(stop_id)
                    seq += 1
                    stop_times_rows.append(
                        {
                            "trip_id": trip_id,
                            "arrival_time": None,
                            "departure_time": None,
                            "stop_id": stop_id,
                            "stop_sequence": seq,
                            "timepoint": 0,
                        }
                    )
            elif mtype == "way" and role in ("", "forward", "backward"):
                geom = m.get("geometry")
                if isinstance(geom, list) and len(geom) >= 2:
                    pts = [(float(p["lat"]), float(p["lon"])) for p in geom if "lat" in p]
                    if len(pts) >= 2:
                        route_ways.append(pts)

        stitched = stitch_way_chain(route_ways)
        way_km = sum_way_lengths_km(route_ways)
        in_bbox_km = sum_in_bbox_way_lengths_km(route_ways, bbox)
        cum_km = 0.0
        for idx, (lat, lon) in enumerate(stitched, start=1):
            if idx > 1:
                prev_lat, prev_lon = stitched[idx - 2]
                step_km = haversine_km(prev_lat, prev_lon, lat, lon)
                if step_km <= 0.5:
                    cum_km += step_km
            shapes_rows.append(
                {
                    "shape_id": shape_id,
                    "shape_pt_lat": round(lat, 6),
                    "shape_pt_lon": round(lon, 6),
                    "shape_pt_sequence": idx,
                    "shape_dist_traveled": round(cum_km, 4),
                }
            )

        routes_rows.append(
            {
                "route_id": route_id,
                "agency_id": agency_id,
                "route_short_name": ref,
                "route_long_name": name,
                "route_type": 3,
                "osm_rel_id": rel_id,
                "network": network,
                "is_hcmc_network": is_hcmc,
                "operator": operator,
                "from_name": rel_tags.get("from", "").strip(),
                "to_name": rel_tags.get("to", "").strip(),
                "is_ptv2": is_ptv2,
                "has_duration": has_duration,
                "opening_hours_raw": oh_raw or "",
                "opening_hours_ok": oh_ok,
                "shape_length_km": round(way_km, 3),
                "in_bbox_length_km": round(in_bbox_km, 3),
            }
        )
        trips_rows.append(
            {
                "route_id": route_id,
                "service_id": "DAILY",
                "trip_id": trip_id,
                "trip_headsign": rel_tags.get("to", "").strip() or name,
                "direction_id": direction_id % 2,
                "shape_id": shape_id if stitched else None,
            }
        )
        freq_rows.append(
            {
                "trip_id": trip_id,
                "start_time": start_time,
                "end_time": end_time,
                "headway_secs": interval.max_s,
                "exact_times": 0,
                "interval_raw": interval.raw or "",
                "interval_min_s": interval.min_s,
                "interval_mid_s": interval.mid_s,
                "interval_max_s": interval.max_s,
                "parse_status": interval.status,
            }
        )

    stops_rows = [stops_by_id[k] for k in sorted(stops_by_id)]
    agency_rows = [
        {
            "agency_id": aid,
            "agency_name": aname,
            "agency_url": "https://www.openstreetmap.org/copyright",
            "agency_timezone": "Asia/Ho_Chi_Minh",
            "agency_lang": "vi",
        }
        for aid, aname in sorted(agencies.items())
    ]

    parquet_dir = out_dir / "gtfs"
    _write_table(routes_rows, ROUTES_SCHEMA, parquet_dir / "routes.parquet")
    _write_table(stops_rows, STOPS_SCHEMA, parquet_dir / "stops.parquet")
    _write_table(trips_rows, TRIPS_SCHEMA, parquet_dir / "trips.parquet")
    _write_table(stop_times_rows, STOP_TIMES_SCHEMA, parquet_dir / "stop_times.parquet")
    _write_table(freq_rows, FREQUENCIES_SCHEMA, parquet_dir / "frequencies.parquet")
    _write_table(shapes_rows, SHAPES_SCHEMA, parquet_dir / "shapes.parquet")

    # Also emit standard GTFS ZIP (frequencies.txt keeps only rows with valid headway_secs)
    valid_freq = [f for f in freq_rows if f["headway_secs"] is not None]
    calendar_rows = [
        {
            "service_id": "DAILY",
            "monday": 1,
            "tuesday": 1,
            "wednesday": 1,
            "thursday": 1,
            "friday": 1,
            "saturday": 1,
            "sunday": 1,
            "start_date": "20260101",
            "end_date": "20261231",
        }
    ]
    feed_info_rows = [
        {
            "feed_publisher_name": "Transitometer CO5173 (derived from OpenStreetMap, ODbL 1.0)",
            "feed_publisher_url": "https://www.openstreetmap.org/copyright",
            "feed_lang": "vi",
            "feed_version": feed_version,
        }
    ]
    zip_path = out_dir / "gtfs_hcmc.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    csv_files: list[tuple[str, bytes]] = [
        (
            "agency.txt",
            _csv_bytes(
                agency_rows,
                ["agency_id", "agency_name", "agency_url", "agency_timezone", "agency_lang"],
            ),
        ),
        (
            "routes.txt",
            _csv_bytes(
                routes_rows,
                ["route_id", "agency_id", "route_short_name", "route_long_name", "route_type"],
            ),
        ),
        (
            "stops.txt",
            _csv_bytes(stops_rows, ["stop_id", "stop_name", "stop_lat", "stop_lon"]),
        ),
        (
            "trips.txt",
            _csv_bytes(
                trips_rows,
                ["route_id", "service_id", "trip_id", "trip_headsign", "direction_id", "shape_id"],
            ),
        ),
        (
            "stop_times.txt",
            _csv_bytes(
                stop_times_rows,
                [
                    "trip_id",
                    "arrival_time",
                    "departure_time",
                    "stop_id",
                    "stop_sequence",
                    "timepoint",
                ],
            ),
        ),
        (
            "frequencies.txt",
            _csv_bytes(
                valid_freq,
                ["trip_id", "start_time", "end_time", "headway_secs", "exact_times"],
            ),
        ),
        (
            "shapes.txt",
            _csv_bytes(
                shapes_rows,
                [
                    "shape_id",
                    "shape_pt_lat",
                    "shape_pt_lon",
                    "shape_pt_sequence",
                    "shape_dist_traveled",
                ],
            ),
        ),
        (
            "calendar.txt",
            _csv_bytes(
                calendar_rows,
                [
                    "service_id",
                    "monday",
                    "tuesday",
                    "wednesday",
                    "thursday",
                    "friday",
                    "saturday",
                    "sunday",
                    "start_date",
                    "end_date",
                ],
            ),
        ),
        (
            "feed_info.txt",
            _csv_bytes(
                feed_info_rows,
                ["feed_publisher_name", "feed_publisher_url", "feed_lang", "feed_version"],
            ),
        ),
    ]
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for fname, data in csv_files:
            info = zipfile.ZipInfo(fname, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)

    return {
        "routes": len(routes_rows),
        "hcmc_network_routes": sum(1 for r in routes_rows if r["is_hcmc_network"]),
        "distinct_refs": len({r["route_short_name"] for r in routes_rows if r["route_short_name"]}),
        "stops": len(stops_rows),
        "stops_in_bbox": sum(1 for s in stops_rows if s["in_bbox"]),
        "stop_times": len(stop_times_rows),
        "frequencies_valid": len(valid_freq),
        "shape_points": len(shapes_rows),
        "zip_bytes": zip_path.stat().st_size,
    }
