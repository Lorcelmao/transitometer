"""Unit tests for OSM HCMC -> frequency-GTFS conversion and open-data quality checks."""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

import duckdb
import pytest

from transitometer.hcmc import load_config
from transitometer.hcmc.osm_to_gtfs import (
    convert_osm_to_gtfs,
    parse_interval,
    parse_opening_hours,
    stitch_way_chain,
    sum_way_lengths_km,
)
from transitometer.hcmc.quality import evaluate_quality


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("00:10-00:20", (600, 900, 1200, "range")),
        ("00:08-00:15", (480, 690, 900, "range")),
        ("01:00", (3600, 3600, 3600, "exact")),
        ("00:15:00", (900, 900, 900, "exact")),
        ("15", (900, 900, 900, "exact")),
        ("15 min", (900, 900, 900, "exact")),
        ("PT12M", (720, 720, 720, "exact")),
        ("00:20-00:10", (600, 900, 1200, "range")),
        ("", (None, None, None, "missing")),
        (None, (None, None, None, "missing")),
        ("frequent", (None, None, None, "unparsed")),
        ("00:00:10", (None, None, None, "out_of_range")),
    ],
)
def test_parse_interval_handles_hcmc_formats(
    raw: str | None, expected: tuple[int | None, int | None, int | None, str]
) -> None:
    spec = parse_interval(raw)
    assert (spec.min_s, spec.mid_s, spec.max_s, spec.status) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Mo-Su 05:00-22:00", ("05:00:00", "22:00:00", True)),
        ("04:45-21:30", ("04:45:00", "21:30:00", True)),
        ("24/7", ("00:00:00", "24:00:00", True)),
        ("", ("05:00:00", "21:00:00", False)),
        ("by appointment", ("05:00:00", "21:00:00", False)),
    ],
)
def test_parse_opening_hours(raw: str, expected: tuple[str, str, bool]) -> None:
    assert parse_opening_hours(raw) == expected


def test_stitch_way_chain_flips_reversed_segments() -> None:
    w1 = [(10.770, 106.690), (10.775, 106.695)]
    w2_reversed = [(10.780, 106.700), (10.775, 106.695)]
    chain = stitch_way_chain([w1, w2_reversed])
    assert chain == [(10.770, 106.690), (10.775, 106.695), (10.780, 106.700)]


def test_stitch_way_chain_reconnects_out_of_order_ways_and_way_sum_ignores_gaps() -> None:
    w_start = [(10.760, 106.680), (10.770, 106.690)]
    w_mid = [(10.770, 106.690), (10.780, 106.700)]
    w_end = [(10.780, 106.700), (10.790, 106.710)]
    # Middle way placed last in OSM relation should still stitch continuously.
    chain = stitch_way_chain([w_start, w_end, w_mid])
    assert chain == [
        (10.760, 106.680),
        (10.770, 106.690),
        (10.780, 106.700),
        (10.790, 106.710),
    ]
    # Disconnected far-away way must not inflate sum_way_lengths_km with a teleport chord.
    w_far = [(10.950, 106.850), (10.955, 106.855)]
    assert sum_way_lengths_km([w_start, w_far]) < 3.0


def _synthetic_osm_bus_doc() -> dict[str, object]:
    """Two HCMC directions for route 08 (range interval) + one route missing interval & duration."""
    return {
        "elements": [
            {"type": "node", "id": 101, "tags": {"name": "ĐH Bách Khoa"}},
            {"type": "node", "id": 102, "tags": {"name": "Ngã tư Hàng Xanh"}},
            {"type": "node", "id": 103, "tags": {}},  # unnamed stop
            {"type": "way", "id": 201, "tags": {"name": "Bến xe Quận 8"}},
            {
                "type": "relation",
                "id": 1001,
                "tags": {
                    "type": "route",
                    "route": "bus",
                    "ref": "08",
                    "name": "Tuyến 08: BX Quận 8 - ĐH Quốc Gia",
                    "network": "Xe buýt Thành phố Hồ Chí Minh",
                    "operator": "FUTA Bus Lines",
                    "from": "Bến xe Quận 8",
                    "to": "ĐH Quốc Gia",
                    "interval": "00:10-00:20",
                    "opening_hours": "Mo-Su 04:40-20:30",
                    "public_transport:version": "2",
                },
                "members": [
                    {
                        "type": "way",
                        "ref": 201,
                        "role": "platform",
                        "geometry": [
                            {"lat": 10.735, "lon": 106.655},
                            {"lat": 10.736, "lon": 106.656},
                        ],
                    },
                    {"type": "node", "ref": 101, "role": "stop", "lat": 10.772, "lon": 106.658},
                    {"type": "node", "ref": 102, "role": "stop", "lat": 10.801, "lon": 106.711},
                    {
                        "type": "way",
                        "ref": 301,
                        "role": "",
                        "geometry": [
                            {"lat": 10.735, "lon": 106.655},
                            {"lat": 10.772, "lon": 106.658},
                        ],
                    },
                    {
                        "type": "way",
                        "ref": 302,
                        "role": "",
                        "geometry": [
                            {"lat": 10.801, "lon": 106.711},
                            {"lat": 10.772, "lon": 106.658},
                        ],
                    },
                ],
            },
            {
                "type": "relation",
                "id": 1002,
                "tags": {
                    "type": "route",
                    "route": "bus",
                    "ref": "08",
                    "name": "Tuyến 08: ĐH Quốc Gia - BX Quận 8",
                    "network": "Xe buýt Thành phố Hồ Chí Minh",
                    "operator": "FUTA Bus Lines",
                    "interval": "00:10-00:15",
                    "opening_hours": "Mo-Su 04:40-20:30",
                    "public_transport:version": "2",
                },
                "members": [
                    {"type": "node", "ref": 102, "role": "stop", "lat": 10.801, "lon": 106.711},
                    {"type": "node", "ref": 101, "role": "stop", "lat": 10.772, "lon": 106.658},
                    {"type": "node", "ref": 103, "role": "stop", "lat": 10.750, "lon": 106.656},
                ],
            },
            {
                "type": "relation",
                "id": 1003,
                "tags": {
                    "type": "route",
                    "route": "bus",
                    "ref": "99",
                    "name": "Tuyến 99 không có interval",
                    "network": "Xe buýt Bình Dương",
                    "operator": "Becamex Tokyu",
                },
                "members": [
                    # Out-of-bbox stop to check filtering
                    {"type": "node", "ref": 999, "role": "stop", "lat": 21.028, "lon": 105.854},
                ],
            },
        ]
    }


def test_convert_osm_to_gtfs_foreign_keys_determinism_and_quality(tmp_path: Path) -> None:
    cfg = load_config()
    doc = _synthetic_osm_bus_doc()
    out1, out2 = tmp_path / "run1", tmp_path / "run2"
    summary1 = convert_osm_to_gtfs(doc, cfg, out1)
    convert_osm_to_gtfs(doc, cfg, out2)

    assert summary1["routes"] == 3
    assert summary1["hcmc_network_routes"] == 2
    assert summary1["frequencies_valid"] == 2
    assert (out1 / "gtfs_hcmc.zip").read_bytes() == (out2 / "gtfs_hcmc.zip").read_bytes()

    # Check GTFS ZIP foreign keys and no fabricated arrival times
    with zipfile.ZipFile(out1 / "gtfs_hcmc.zip") as zf:

        def read_csv(name: str) -> list[dict[str, str]]:
            return list(csv.DictReader(io.StringIO(zf.read(name).decode("utf-8"))))

        routes = {r["route_id"] for r in read_csv("routes.txt")}
        stops = {s["stop_id"] for s in read_csv("stops.txt")}
        trips = read_csv("trips.txt")
        trip_ids = {t["trip_id"] for t in trips}
        stop_times = read_csv("stop_times.txt")
        freqs = read_csv("frequencies.txt")

        assert all(t["route_id"] in routes for t in trips)
        assert all(st["trip_id"] in trip_ids and st["stop_id"] in stops for st in stop_times)
        assert all(st["arrival_time"] == "" and st["departure_time"] == "" for st in stop_times)
        assert all(f["trip_id"] in trip_ids and f["exact_times"] == "0" for f in freqs)
        # Conservative upper bound: 00:10-00:20 -> 1200 s; 00:10-00:15 -> 900 s
        headways = {f["trip_id"]: int(f["headway_secs"]) for f in freqs}
        assert headways == {"trip_1001": 1200, "trip_1002": 900}

    # Check stitched shape length is positive (~8-9 km for route 1001)
    with duckdb.connect() as con:
        km = con.execute(
            f"SELECT shape_length_km FROM '{(out1 / 'gtfs' / 'routes.parquet').as_posix()}'"
            " WHERE route_id = 'osm_1001'"
        ).fetchone()
    assert km is not None and 5.0 < float(km[0]) < 15.0

    # Quality audit on primary HCMC network vs all bbox
    q_rows = evaluate_quality(out1 / "gtfs", out1 / "hcmc_data_quality.parquet")
    hcmc_q = {r["metric"]: r for r in q_rows if r["scope"] == "hcmc_network"}
    assert hcmc_q["interval_parsed_share"]["passed"] is True
    assert hcmc_q["bidirectional_ref_share"]["value"] == pytest.approx(1.0)
    assert hcmc_q["duration_present_share"]["passed"] is False  # 0% duration -> expected fail
    assert hcmc_q["named_stop_share"]["numerator"] == 3
    assert hcmc_q["named_stop_share"]["denominator"] == 4
