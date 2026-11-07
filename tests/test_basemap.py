"""The stop map's background: line simplification, network merging and the committed file."""

from __future__ import annotations

import json

from transitometer.serve import basemap


def test_simplify_keeps_the_ends_and_drops_points_on_the_line() -> None:
    line = [(0.0, 0.0), (1.0, 0.00001), (2.0, 0.0), (3.0, 1.0)]
    assert basemap.simplify(line, eps=0.001) == [(0.0, 0.0), (2.0, 0.0), (3.0, 1.0)]
    assert basemap.simplify(line[:2], eps=10.0) == line[:2]


def test_merge_keeps_a_shared_segment_once() -> None:
    # Two routes run along the same street in opposite directions, one continues further.
    a = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]
    b = [(2.0, 0.0), (1.0, 0.0), (0.0, 0.0), (0.0, 1.0)]
    merged = basemap.merge([a, b], grid=1.0)
    segments = {frozenset(pair) for line in merged for pair in zip(line, line[1:], strict=False)}
    assert segments == {
        frozenset({(0.0, 0.0), (1.0, 0.0)}),
        frozenset({(1.0, 0.0), (2.0, 0.0)}),
        frozenset({(0.0, 0.0), (0.0, 1.0)}),
    }
    assert sum(len(line) - 1 for line in merged) == 3


def test_merge_walks_a_closed_loop() -> None:
    loop = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)]
    merged = basemap.merge([loop], grid=1.0)
    assert len(merged) == 1 and len(merged[0]) == 5


def test_the_committed_basemap_covers_new_york() -> None:
    data = json.loads(basemap.OUT.read_text(encoding="utf-8"))
    assert data["schema"] == basemap.SCHEMA
    assert data["streets"] and data["subway"]
    points = [p for line in data["streets"] for p in line]
    points += [p for s in data["subway"] for line in s["lines"] for p in line]
    assert all(-74.6 < lon < -73.4 and 40.4 < lat < 41.2 for lon, lat in points)
    assert all(s["color"].startswith("#") and len(s["color"]) == 7 for s in data["subway"])
