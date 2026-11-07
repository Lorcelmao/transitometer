"""The stop map's background, drawn from the MTA static timetables: no map tiles, no third party.

`python tasks.py web-basemap` reads the route shapes of the pinned schedule versions in the landing
zone and writes web/public/basemap/nyc.json:

- streets: every bus route shape, simplified (bus routes trace the street grid);
- subway: the subway route shapes, merged into one network per line colour.

The file is reference geometry, not a metric, so it lives outside web/public/data (which
`web-data` regenerates from the snapshot). The output is deterministic: shapes in shape_id order,
coordinates rounded, compact JSON.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import duckdb

from transitometer.ingest.sources import Sources, schedule_dir
from transitometer.serve import kpis

SCHEMA = "transitometer.basemap/1"
OUT = kpis.REPO / "web" / "public" / "basemap" / "nyc.json"

Point = tuple[float, float]  # (lon, lat)

# Simplification tolerances in degrees (about 10 m and 7 m at New York's latitude).
STREET_EPS = 0.00012
SUBWAY_EPS = 0.00008
SUBWAY_GRID = 0.00005  # snapping grid that merges subway shapes sharing a track
FALLBACK_COLOR = "808183"  # the MTA's grey, for a route without a colour


def simplify(points: Sequence[Point], eps: float) -> list[Point]:
    """Ramer-Douglas-Peucker (iterative): drop points closer than `eps` to the kept line."""
    if len(points) < 3:
        return list(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        (x1, y1), (x2, y2) = points[a], points[b]
        dx, dy = x2 - x1, y2 - y1
        norm = (dx * dx + dy * dy) ** 0.5 or 1e-12
        best, index = -1.0, -1
        for i in range(a + 1, b):
            x0, y0 = points[i]
            distance = abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1) / norm
            if distance > best:
                best, index = distance, i
        if best > eps:
            keep[index] = True
            stack += [(a, index), (index, b)]
    return [p for p, k in zip(points, keep, strict=True) if k]


def merge(polylines: Iterable[Sequence[Point]], grid: float) -> list[list[Point]]:
    """One network from overlapping polylines: snap points to a grid, keep each segment once,
    then walk chains between junctions (and around loops) back into polylines."""
    adjacent: dict[tuple[int, int], set[tuple[int, int]]] = {}
    for line in polylines:
        nodes = [(round(x / grid), round(y / grid)) for x, y in line]
        for a, b in zip(nodes, nodes[1:], strict=False):
            if a != b:
                adjacent.setdefault(a, set()).add(b)
                adjacent.setdefault(b, set()).add(a)
    seen: set[frozenset[tuple[int, int]]] = set()

    def walk(start: tuple[int, int], step: tuple[int, int]) -> list[tuple[int, int]]:
        chain = [start, step]
        seen.add(frozenset((start, step)))
        previous, current = start, step
        while len(adjacent[current]) == 2:
            (following,) = adjacent[current] - {previous}
            edge = frozenset((current, following))
            if edge in seen:
                break
            seen.add(edge)
            chain.append(following)
            previous, current = current, following
        return chain

    ends = sorted(n for n in adjacent if len(adjacent[n]) != 2)
    chains = [
        walk(node, step)
        for node in [*ends, *sorted(adjacent)]  # junctions and line ends first, then loops
        for step in sorted(adjacent[node])
        if frozenset((node, step)) not in seen
    ]
    return [[(x * grid, y * grid) for x, y in chain] for chain in chains]


def _round(line: Sequence[Point], digits: int) -> list[list[float]]:
    out: list[list[float]] = []
    for x, y in line:
        point = [round(x, digits), round(y, digits)]
        if not out or out[-1] != point:
            out.append(point)
    return out


def _shapes(paths: list[Path], trips: list[Path] | None = None) -> list[tuple[Any, ...]]:
    """Each shape's points in sequence order; with trips, also its route's colour."""
    files = ", ".join(f"'{p.as_posix()}'" for p in paths)
    points = (
        "list(struct_pack(x := s.shape_pt_lon::DOUBLE, y := s.shape_pt_lat::DOUBLE)"
        " ORDER BY s.shape_pt_sequence::INT) AS pts"
    )
    if trips is None:
        sql = f"SELECT s.shape_id, {points} FROM read_parquet([{files}]) s GROUP BY ALL ORDER BY 1"
    else:
        trip_files = ", ".join(f"'{p.as_posix()}'" for p in trips)
        route_files = ", ".join(f"'{p.with_name('routes.parquet').as_posix()}'" for p in trips)
        sql = (
            f"SELECT s.shape_id, any_value(r.route_color) AS color, {points}"
            f" FROM read_parquet([{files}]) s"
            # one route per shape, so a shape shared by two routes is not doubled by the join
            f" JOIN (SELECT shape_id, min(route_id) AS route_id FROM read_parquet([{trip_files}])"
            " GROUP BY shape_id) t"
            f" USING (shape_id) JOIN read_parquet([{route_files}]) r USING (route_id)"
            " GROUP BY s.shape_id ORDER BY 1"
        )
    return duckdb.sql(sql).fetchall()


def build(landing: Path, sources: Sources) -> dict[str, Any]:
    """The basemap of the pinned schedule versions in `landing`."""

    def tables(group: str, table: str) -> list[Path]:
        paths = [
            landing / schedule_dir(v) / f"{table}.parquet"
            for v in sources.schedules
            if v.group == group
        ]
        missing = [p for p in paths if not p.exists()]
        if not paths or missing:
            raise FileNotFoundError(f"{group} {table}: run `python tasks.py fetch` ({missing})")
        return paths

    streets = [
        _round(simplify([(p["x"], p["y"]) for p in pts], STREET_EPS), 4)
        for _, pts in _shapes(tables("bus", "shapes"))
    ]
    by_color: dict[str, list[list[Point]]] = {}
    for _, color, pts in _shapes(tables("subway", "shapes"), tables("subway", "trips")):
        key = f"#{(color or FALLBACK_COLOR).strip().lower()}"
        by_color.setdefault(key, []).append([(p["x"], p["y"]) for p in pts])
    subway = [
        {
            "color": color,
            "lines": [_round(simplify(c, SUBWAY_EPS), 5) for c in merge(lines, SUBWAY_GRID)],
        }
        for color, lines in sorted(by_color.items())
    ]
    return {
        "schema": SCHEMA,
        "source": "MTA static GTFS route shapes (bus and subway), the pinned schedule versions",
        "streets": streets,
        "subway": subway,
    }


def write(basemap: dict[str, Any], out: Path = OUT) -> dict[str, int]:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(basemap, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n"
    )
    return {
        "streets": len(basemap["streets"]),
        "subway_lines": sum(len(s["lines"]) for s in basemap["subway"]),
        "points": sum(len(line) for line in basemap["streets"])
        + sum(len(line) for s in basemap["subway"] for line in s["lines"]),
        "bytes": out.stat().st_size,
    }
