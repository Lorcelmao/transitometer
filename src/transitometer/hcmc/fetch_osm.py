"""Fetch HCMC bus routes and administrative ward polygons from OpenStreetMap into landing/hcmc/.

Pins both static JSON snapshots into data-manifest.json with kind='case_study' and SHA-256
checksums so downstream conversion and DuckDB Spatial analytics run completely offline.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from transitometer.hcmc import HcmcConfig
from transitometer.ingest.fetch import (
    ManifestEntry,
    download,
    load_manifest,
    save_manifest,
    sha256_file,
)

USER_AGENT = "Transitometer-CO5173/1.0 (+https://github.com/Lorcelmao/transitometer)"
RETRYABLE_HTTP = {429, 500, 502, 503, 504}


def _http_get_json(url: str, timeout: int = 45, retries: int = 3) -> dict[str, Any]:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
                return data
        except urllib.error.HTTPError as exc:
            last_err = exc
            if exc.code not in RETRYABLE_HTTP:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last_err = exc
        time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"GET {url} failed after {retries} attempts: {last_err}")


def _overpass_query(
    ql: str,
    endpoints: tuple[str, ...],
    timeout: int = 45,
    retries: int = 3,
    log: Callable[[str], None] = lambda _: None,
) -> dict[str, Any]:
    body = urllib.parse.urlencode({"data": ql}).encode("utf-8")
    last_err: Exception | None = None
    for attempt in range(retries):
        for endpoint in endpoints:
            try:
                req = urllib.request.Request(
                    endpoint,
                    data=body,
                    headers={"User-Agent": USER_AGENT},
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
                    return data
            except urllib.error.HTTPError as exc:
                last_err = exc
                log(f"    [{endpoint}] HTTP {exc.code}; trying next mirror")
                if exc.code not in RETRYABLE_HTTP:
                    continue
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                last_err = exc
                log(f"    [{endpoint}] {type(exc).__name__}: {exc}; trying next mirror")
        time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"Overpass query failed across all endpoints: {last_err}")


def bus_route_ids_query(cfg: HcmcConfig) -> str:
    """Lightweight ID-only listing of bus route relations inside the core HCMC bbox."""
    bb = cfg.bbox.overpass()
    return f'[out:json][timeout:30];\nrel["type"="route"]["route"="bus"]({bb});\nout ids;\n'


def bus_routes_chunk_query(rel_ids: list[int]) -> str:
    """Fetch geometry + direct stop/platform tags for a batch of bus route relations."""
    ids = ",".join(str(i) for i in rel_ids)
    return (
        "[out:json][timeout:45];\n"
        f"rel(id:{ids})->.r;\n"
        ".r out geom;\n"
        "node(r.r);\n"
        "out tags;\n"
        'way(r.r:"platform");\n'
        "out tags;\n"
    )


def ward_chunk_query(rel_ids: list[int]) -> str:
    ids = ",".join(str(i) for i in rel_ids)
    return f"[out:json][timeout:45];\nrel(id:{ids});\nout geom;\n"


def _write_json_deterministic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    tmp.replace(path)


def _record_manifest(
    manifest_path: Path,
    relpath: str,
    dest: Path,
    url: str,
    license_text: str,
    retrieved_utc: str,
) -> ManifestEntry:
    entries = load_manifest(manifest_path)
    entry = ManifestEntry(
        url=url,
        sha256=sha256_file(dest),
        bytes=dest.stat().st_size,
        rows=None,
        kind="case_study",
        source="osm_hcmc",
        license=license_text,
        retrieved_utc=retrieved_utc,
    )
    entries[relpath] = entry
    save_manifest(manifest_path, entries)
    return entry


def fetch_hcmc_pbf(
    cfg: HcmcConfig,
    landing: Path,
    manifest_path: Path,
    force: bool = False,
    log: Callable[[str], None] = lambda msg: print(msg, flush=True),
) -> dict[str, Any]:
    """Download Geofabrik vietnam-latest.osm.pbf once, pin SHA-256, and extract HCMC JSONs."""
    from transitometer.hcmc.extract_pbf import extract_from_pbf

    existing = load_manifest(manifest_path)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    pbf_rel = "hcmc/vietnam-latest.osm.pbf"
    pbf_dest = landing / pbf_rel
    pbf_known = existing.get(pbf_rel)

    if force or not pbf_dest.exists():
        log(f"downloading {cfg.fallback_geofabrik_pbf} -> {pbf_dest} ...")
        download(cfg.fallback_geofabrik_pbf, pbf_dest)
    if pbf_known is None or force or pbf_dest.stat().st_size != pbf_known.bytes:
        pbf_entry = _record_manifest(
            manifest_path,
            pbf_rel,
            pbf_dest,
            cfg.fallback_geofabrik_pbf,
            cfg.license,
            now,
        )
        log(f"pinned {pbf_rel} ({pbf_entry.bytes / 1e6:.2f} MB, sha256={pbf_entry.sha256[:12]})")
    else:
        pbf_entry = pbf_known
        log(f"reusing {pbf_rel} ({pbf_entry.bytes / 1e6:.2f} MB, sha256={pbf_entry.sha256[:12]})")

    bus_dest = landing / cfg.bus_routes_relpath
    wards_dest = landing / cfg.admin_wards_relpath
    extracted = extract_from_pbf(pbf_dest, cfg, bus_dest, wards_dest, log=log)
    bus_entry = _record_manifest(
        manifest_path,
        cfg.bus_routes_relpath,
        bus_dest,
        f"{cfg.fallback_geofabrik_pbf}#hcmc_bus_routes",
        cfg.license,
        pbf_entry.retrieved_utc,
    )
    wards_entry = _record_manifest(
        manifest_path,
        cfg.admin_wards_relpath,
        wards_dest,
        f"{cfg.fallback_geofabrik_pbf}#relation/{cfg.osm_city_relation_id}",
        cfg.license,
        pbf_entry.retrieved_utc,
    )
    return {
        "pbf": {"bytes": pbf_entry.bytes, "sha256": pbf_entry.sha256},
        "bus_routes": {
            "bytes": bus_entry.bytes,
            "sha256": bus_entry.sha256,
            "relations": extracted["bus_relations"],
        },
        "admin_wards": {
            "bytes": wards_entry.bytes,
            "sha256": wards_entry.sha256,
            "wards": extracted["wards"],
            "expected_subareas": extracted["expected_subareas"],
        },
    }


def fetch_hcmc(
    cfg: HcmcConfig,
    landing: Path,
    manifest_path: Path,
    force: bool = False,
    source: str = "geofabrik",
    log: Callable[[str], None] = lambda msg: print(msg, flush=True),
) -> dict[str, Any]:
    """Download HCMC OSM inputs into landing/hcmc/ and pin checksums in data-manifest.json."""
    if source == "geofabrik":
        return fetch_hcmc_pbf(cfg, landing, manifest_path, force=force, log=log)
    existing = load_manifest(manifest_path)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    summary: dict[str, Any] = {}

    # 1. Bus routes + stop/platform tags (chunked by 50 relations for reliability)
    bus_dest = landing / cfg.bus_routes_relpath
    bus_known = existing.get(cfg.bus_routes_relpath)
    if (
        not force
        and bus_dest.exists()
        and bus_known is not None
        and bus_dest.stat().st_size == bus_known.bytes
        and sha256_file(bus_dest) == bus_known.sha256
    ):
        log(f"skipped {cfg.bus_routes_relpath} (checksum unchanged)")
        summary["bus_routes"] = {"status": "skipped", "bytes": bus_known.bytes}
    else:
        log("listing OSM HCMC bus route relation IDs ...")
        id_doc = _overpass_query(bus_route_ids_query(cfg), cfg.overpass_endpoints, log=log)
        bus_ids = sorted(
            int(e["id"]) for e in id_doc.get("elements", []) if e.get("type") == "relation"
        )
        log(f"found {len(bus_ids)} bus route relations; fetching geometry in chunks of 50 ...")
        dedup_elements: dict[tuple[str, int], dict[str, Any]] = {}
        chunk_size = 50
        n_bus_chunks = (len(bus_ids) + chunk_size - 1) // chunk_size
        osm3s_meta: dict[str, Any] = id_doc.get("osm3s", {})
        for i in range(0, len(bus_ids), chunk_size):
            chunk = bus_ids[i : i + chunk_size]
            log(f"  bus chunk {i // chunk_size + 1}/{n_bus_chunks} ({len(chunk)} rels)")
            chunk_raw = _overpass_query(
                bus_routes_chunk_query(chunk), cfg.overpass_endpoints, log=log
            )
            for elem in chunk_raw.get("elements", []):
                key = (str(elem.get("type", "")), int(elem.get("id", 0)))
                # Prefer full geometry/member object over tag-only object if same key appears.
                prev = dedup_elements.get(key)
                if prev is None or len(elem) > len(prev):
                    dedup_elements[key] = elem
            if i + chunk_size < len(bus_ids):
                time.sleep(1.0)
        elements = [dedup_elements[k] for k in sorted(dedup_elements)]
        payload = {
            "schema": "transitometer.osm-bus/1",
            "bbox": cfg.bbox.overpass(),
            "osm3s": osm3s_meta,
            "elements": elements,
        }
        _write_json_deterministic(bus_dest, payload)
        entry = _record_manifest(
            manifest_path,
            cfg.bus_routes_relpath,
            bus_dest,
            f"{cfg.overpass_endpoints[0]}#hcmc_bus_routes",
            cfg.license,
            now,
        )
        rels = sum(1 for e in elements if e.get("type") == "relation")
        log(f"fetched {cfg.bus_routes_relpath} ({entry.bytes / 1e6:.2f} MB, {rels} relations)")
        summary["bus_routes"] = {
            "status": "downloaded",
            "bytes": entry.bytes,
            "sha256": entry.sha256,
            "relations": rels,
        }

    # 2. Administrative wards (168 subareas of relation/1973756, post-2025 HCMC boundary)
    wards_dest = landing / cfg.admin_wards_relpath
    wards_known = existing.get(cfg.admin_wards_relpath)
    if (
        not force
        and wards_dest.exists()
        and wards_known is not None
        and wards_dest.stat().st_size == wards_known.bytes
        and sha256_file(wards_dest) == wards_known.sha256
    ):
        log(f"skipped {cfg.admin_wards_relpath} (checksum unchanged)")
        summary["admin_wards"] = {"status": "skipped", "bytes": wards_known.bytes}
    else:
        city_url = f"{cfg.osm_api_base}/relation/{cfg.osm_city_relation_id}.json"
        log(f"fetching HCMC boundary metadata from {city_url} ...")
        city_doc = _http_get_json(city_url)
        city_rel = city_doc["elements"][0]
        subarea_ids = sorted(
            int(m["ref"])
            for m in city_rel.get("members", [])
            if m.get("type") == "relation" and m.get("role") == "subarea"
        )
        log(f"found {len(subarea_ids)} subarea ward/commune relations; fetching in chunks ...")
        all_wards: list[dict[str, Any]] = []
        step = max(1, cfg.ward_chunk_size)
        n_chunks = (len(subarea_ids) + step - 1) // step
        for i in range(0, len(subarea_ids), step):
            chunk = subarea_ids[i : i + step]
            log(f"  wards chunk {i // step + 1}/{n_chunks} ({len(chunk)} rels)")
            chunk_raw = _overpass_query(ward_chunk_query(chunk), cfg.overpass_endpoints, log=log)
            all_wards.extend(
                e for e in chunk_raw.get("elements", []) if e.get("type") == "relation"
            )
            if i + step < len(subarea_ids):
                time.sleep(1.0)
        all_wards.sort(key=lambda e: int(e.get("id", 0)))
        ward_payload = {
            "schema": "transitometer.osm-wards/1",
            "city_relation_id": cfg.osm_city_relation_id,
            "city_version": city_rel.get("version"),
            "city_timestamp": city_rel.get("timestamp"),
            "city_tags": city_rel.get("tags", {}),
            "subarea_count": len(subarea_ids),
            "elements": all_wards,
        }
        _write_json_deterministic(wards_dest, ward_payload)
        entry = _record_manifest(
            manifest_path,
            cfg.admin_wards_relpath,
            wards_dest,
            city_url,
            cfg.license,
            now,
        )
        log(
            f"fetched {cfg.admin_wards_relpath} "
            f"({entry.bytes / 1e6:.2f} MB, {len(all_wards)}/{len(subarea_ids)} wards)"
        )
        summary["admin_wards"] = {
            "status": "downloaded",
            "bytes": entry.bytes,
            "sha256": entry.sha256,
            "wards": len(all_wards),
            "expected_subareas": len(subarea_ids),
        }

    return summary
