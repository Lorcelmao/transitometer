"""Open-data quality checks for OSM HCMC bus network (BR11 counterpart to BR7 feed health).

Evaluates 8 declared completeness and structural checks on the derived frequency-GTFS Parquet
tables, reporting both the primary HCMC bus network and the full bounding box.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq


@dataclass(frozen=True)
class QualityCheck:
    metric: str
    label: str
    threshold: float
    description: str


CHECKS: tuple[QualityCheck, ...] = (
    QualityCheck(
        "ref_coverage",
        "Route number (ref) present",
        0.95,
        "Share of bus route relations carrying a route number (ref).",
    ),
    QualityCheck(
        "interval_parsed_share",
        "Headway (interval) parsed",
        0.85,
        "Share of route relations with a parseable headway (interval single or range).",
    ),
    QualityCheck(
        "opening_hours_parsed_share",
        "Service span (opening_hours) parsed",
        0.90,
        "Share of route relations with parseable operating hours.",
    ),
    QualityCheck(
        "ptv2_share",
        "PTv2 schema tagged",
        0.60,
        "Share of route relations mapped under Public Transport v2 (public_transport:version=2).",
    ),
    QualityCheck(
        "duration_present_share",
        "Trip duration tagged",
        0.50,
        "Share of route relations with a duration tag (low share explains why stop arrival "
        "times are not interpolated).",
    ),
    QualityCheck(
        "stops_valid_share",
        "Routes with at least 2 stops in HCMC",
        0.95,
        "Share of route relations having at least 2 located stops inside the HCMC study area.",
    ),
    QualityCheck(
        "bidirectional_ref_share",
        "Routes mapped in at least 2 directions",
        0.80,
        "Share of distinct route numbers (ref) having at least two directional relations.",
    ),
    QualityCheck(
        "named_stop_share",
        "Located stops with names",
        0.80,
        "Share of study-area stops carrying a non-empty stop_name tag.",
    ),
)

QUALITY_SCHEMA = pa.schema(
    [
        ("scope", pa.string()),
        ("metric", pa.string()),
        ("label", pa.string()),
        ("value", pa.float64()),
        ("numerator", pa.int64()),
        ("denominator", pa.int64()),
        ("threshold", pa.float64()),
        ("passed", pa.bool_()),
        ("description", pa.string()),
    ]
)


def _scan(path: Path) -> str:
    return "'" + path.as_posix().replace("'", "''") + "'"


def evaluate_quality(gtfs_dir: Path, out_path: Path | None = None) -> list[dict[str, Any]]:
    """Compute the 8 quality checks for 'hcmc_network' and 'all_bbox' scopes."""
    routes_p = _scan(gtfs_dir / "routes.parquet")
    stops_p = _scan(gtfs_dir / "stops.parquet")
    trips_p = _scan(gtfs_dir / "trips.parquet")
    st_p = _scan(gtfs_dir / "stop_times.parquet")
    freq_p = _scan(gtfs_dir / "frequencies.parquet")

    rows: list[dict[str, Any]] = []
    with duckdb.connect() as con:
        for scope, where in (
            ("hcmc_network", "r.is_hcmc_network = true"),
            ("all_bbox", "true"),
        ):
            r_stats = con.execute(
                f"""
                WITH rels AS (
                    SELECT r.*, f.headway_secs,
                           (SELECT count(DISTINCT st.stop_id)
                            FROM read_parquet({trips_p}) t
                            JOIN read_parquet({st_p}) st USING (trip_id)
                            JOIN read_parquet({stops_p}) s USING (stop_id)
                            WHERE t.route_id = r.route_id AND s.in_bbox) AS valid_stops
                    FROM read_parquet({routes_p}) r
                    LEFT JOIN read_parquet({trips_p}) t ON t.route_id = r.route_id
                    LEFT JOIN read_parquet({freq_p}) f ON f.trip_id = t.trip_id
                    WHERE {where}
                ),
                by_ref AS (
                    SELECT route_short_name, count(*) AS dirs
                    FROM rels WHERE route_short_name <> ''
                    GROUP BY route_short_name
                ),
                used_stops AS (
                    SELECT DISTINCT s.stop_id, s.stop_name
                    FROM rels r
                    JOIN read_parquet({trips_p}) t ON t.route_id = r.route_id
                    JOIN read_parquet({st_p}) st USING (trip_id)
                    JOIN read_parquet({stops_p}) s USING (stop_id)
                    WHERE s.in_bbox
                )
                SELECT
                    count(*) AS n_rels,
                    count(*) FILTER (WHERE route_short_name <> '') AS n_ref,
                    count(*) FILTER (WHERE headway_secs IS NOT NULL) AS n_interval,
                    count(*) FILTER (WHERE opening_hours_ok) AS n_oh,
                    count(*) FILTER (WHERE is_ptv2) AS n_ptv2,
                    count(*) FILTER (WHERE has_duration) AS n_dur,
                    count(*) FILTER (WHERE valid_stops >= 2) AS n_valid_stops,
                    (SELECT count(*) FROM by_ref) AS n_refs,
                    (SELECT count(*) FROM by_ref WHERE dirs >= 2) AS n_bidir,
                    (SELECT count(*) FROM used_stops) AS n_stops,
                    (SELECT count(*) FROM used_stops WHERE stop_name <> '') AS n_named_stops
                FROM rels
                """
            ).fetchone()
            assert r_stats is not None
            (
                n_rels,
                n_ref,
                n_interval,
                n_oh,
                n_ptv2,
                n_dur,
                n_valid_stops,
                n_refs,
                n_bidir,
                n_stops,
                n_named_stops,
            ) = [int(x) for x in r_stats]

            pairs = {
                "ref_coverage": (n_ref, n_rels),
                "interval_parsed_share": (n_interval, n_rels),
                "opening_hours_parsed_share": (n_oh, n_rels),
                "ptv2_share": (n_ptv2, n_rels),
                "duration_present_share": (n_dur, n_rels),
                "stops_valid_share": (n_valid_stops, n_rels),
                "bidirectional_ref_share": (n_bidir, n_refs),
                "named_stop_share": (n_named_stops, n_stops),
            }
            for check in CHECKS:
                num, den = pairs[check.metric]
                val = (num / den) if den > 0 else 0.0
                rows.append(
                    {
                        "scope": scope,
                        "metric": check.metric,
                        "label": check.label,
                        "value": round(val, 6),
                        "numerator": num,
                        "denominator": den,
                        "threshold": check.threshold,
                        "passed": val >= check.threshold,
                        "description": check.description,
                    }
                )

    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cols = {f.name: [r[f.name] for r in rows] for f in QUALITY_SCHEMA}
        pq.write_table(pa.table(cols, schema=QUALITY_SCHEMA), out_path)
    return rows
