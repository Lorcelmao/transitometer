"""BR11 case study: Ho Chi Minh City static bus coverage from OpenStreetMap + DuckDB Spatial.

Kept strictly independent from the MTA real-time Kafka/Spark/Delta pipeline so MTA snapshots,
golden parity and tests are unaffected. Derived OSM tables follow ODbL 1.0 (see
docs/hcmc-odbl-notice.md).
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = REPO / "config" / "hcmc_sources.json"
DEFAULT_CORE_WARDS = REPO / "config" / "hcmc_core_wards.json"


def normalize_ward_name(name: str) -> str:
    """Normalize Vietnamese ward/commune names to Unicode NFC with single spaces."""
    return " ".join(unicodedata.normalize("NFC", name).split())


@dataclass(frozen=True)
class CoreWardsSpec:
    resolution: str
    resolution_date: str
    effective_date: str
    official_pre_merger_area_km2: float
    ward_names: frozenset[str]
    ordered_names: tuple[str, ...]
    former_district_by_name: dict[str, str]


def load_core_wards(path: Path = DEFAULT_CORE_WARDS) -> CoreWardsSpec:
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    ordered: list[str] = []
    districts: dict[str, str] = {}
    for entry in raw["wards"]:
        name = normalize_ward_name(str(entry["name"]))
        ordered.append(name)
        districts[name] = str(entry.get("former_district", ""))
    return CoreWardsSpec(
        resolution=str(raw["resolution"]),
        resolution_date=str(raw["resolution_date"]),
        effective_date=str(raw["effective_date"]),
        official_pre_merger_area_km2=float(raw["official_pre_merger_area_km2"]),
        ward_names=frozenset(ordered),
        ordered_names=tuple(ordered),
        former_district_by_name=districts,
    )


@dataclass(frozen=True)
class BBox:
    south: float
    west: float
    north: float
    east: float

    def overpass(self) -> str:
        return f"{self.south},{self.west},{self.north},{self.east}"

    def contains(self, lat: float, lon: float) -> bool:
        return self.south <= lat <= self.north and self.west <= lon <= self.east


@dataclass(frozen=True)
class HcmcConfig:
    city: str
    osm_city_relation_id: int
    bbox: BBox
    primary_network: str
    license: str
    attribution: str
    crs: str
    walk_radius_m: float
    frequent_buses_per_hour: float
    osm_api_base: str
    overpass_endpoints: tuple[str, ...]
    fallback_geofabrik_pbf: str
    ward_chunk_size: int
    bus_routes_relpath: str
    admin_wards_relpath: str


def load_config(path: Path = DEFAULT_CONFIG) -> HcmcConfig:
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    bb = raw["bbox"]
    files = raw["landing_files"]
    return HcmcConfig(
        city=str(raw["city"]),
        osm_city_relation_id=int(raw["osm_city_relation_id"]),
        bbox=BBox(
            south=float(bb["south"]),
            west=float(bb["west"]),
            north=float(bb["north"]),
            east=float(bb["east"]),
        ),
        primary_network=str(raw["primary_network"]),
        license=str(raw["license"]),
        attribution=str(raw["attribution"]),
        crs=str(raw["crs"]),
        walk_radius_m=float(raw["walk_radius_m"]),
        frequent_buses_per_hour=float(raw["frequent_buses_per_hour"]),
        osm_api_base=str(raw["osm_api_base"]).rstrip("/"),
        overpass_endpoints=tuple(str(u) for u in raw["overpass_endpoints"]),
        fallback_geofabrik_pbf=str(raw["fallback_geofabrik_pbf"]),
        ward_chunk_size=int(raw["ward_chunk_size"]),
        bus_routes_relpath=str(files["bus_routes"]),
        admin_wards_relpath=str(files["admin_wards"]),
    )
