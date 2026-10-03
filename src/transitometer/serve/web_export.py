"""Static JSON for the Next.js site: every view, for every filter combination, from the snapshot.

`python tasks.py web-data` runs the views of transitometer.serve.views over the validated snapshot
(showcase/data/) and writes web/public/data/, the evidence copies to web/public/evidence/, and
showcase/contract/parity-expected.json: the display strings both frontends must show. The site
only displays these files, so it cannot compute a metric differently from Streamlit.

The output is deterministic (sorted keys, no generation timestamps, floats as Python writes them),
so `web-data --check` can regenerate it and fail on any byte difference.
"""

from __future__ import annotations

import filecmp
import json
import math
import re
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from transitometer.serve import kpis, snapshot, views
from transitometer.serve.format import day_label

SCHEMA = "transitometer.web/1"
WEB_DATA = kpis.REPO / "web" / "public" / "data"
WEB_EVIDENCE = kpis.REPO / "web" / "public" / "evidence"
PARITY = kpis.REPO / "showcase" / "contract" / "parity-expected.json"
MODES = tuple(views.GROUPS)


class ExportError(Exception):
    """The snapshot cannot be published; nothing was written."""


@dataclass(frozen=True)
class Page:
    """Where a view is shown in each frontend, and the tables it reads (named on the page)."""

    streamlit: str
    route: str
    tables: tuple[str, ...]


# Every page both frontends show; keys are the JSON folder or file names.
PAGES = {
    "overview": Page(
        "Overview",
        "/",
        ("otp_summary", "headway_summary", "missing_trip_summary", "feed_quality_score"),
    ),
    "on-time": Page("On-time performance", "/reliability/on-time/", ("otp_route_hour",)),
    "headways": Page(
        "Headways and bunching",
        "/reliability/headways/",
        ("headway_summary", "headway_regularity"),
    ),
    "missing-trips": Page(
        "Missing trips",
        "/reliability/missing-trips/",
        ("missing_trip_summary", "missing_by_route", "feed_quality_metrics"),
    ),
    "scorecards": Page("Route scorecards", "/diagnostics/route-scorecards/", ("route_scorecard",)),
    "stops": Page(
        "Stop reliability", "/diagnostics/stops/", ("stop_hour_reliability", "stop_names")
    ),
    "delay": Page(
        "Where delay builds up",
        "/diagnostics/delay/",
        ("delay_attribution_summary", "segment_travel_stats", "stop_names"),
    ),
    "early-warning": Page(
        "Early warning", "/diagnostics/early-warning/", ("early_warning_summary",)
    ),
    "map": Page(
        "",  # the site only: a map needs the browser, Streamlit has the stop explorer
        "/diagnostics/map/",
        ("stop_hour_reliability", "stop_locations", "stop_names"),
    ),
    "feed-health": Page(
        "Feed health", "/data/feed-health/", ("feed_quality_score", "feed_quality_metrics")
    ),
    "validation": Page("Data & validation", "/data/validation/", ()),
}


def route_file(route_id: str) -> str:
    """A route id as a file name safe in URLs: 'M15+' -> 'M15_2b' (reversible, no collisions)."""
    return re.sub(r"[^A-Za-z0-9-]", lambda m: f"_{ord(m.group()):x}", route_id)


def _clean(value: Any) -> Any:
    """JSON-safe values: NaN -> null; containers recursively; anything unexpected is an error."""
    if isinstance(value, float):
        return None if math.isnan(value) else value
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_clean(v) for v in value]
    if value is None or isinstance(value, bool | int | str):
        return value
    raise ExportError(f"cannot export a {type(value).__name__} value: {value!r}")


def _dump(data: Any) -> str:
    return json.dumps(_clean(data), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class _Writer:
    """Writes enveloped view files under one folder and collects the parity expectations."""

    def __init__(self, out: Path, manifest: dict[str, Any]) -> None:
        self.out, self.manifest = out, manifest
        self.parity: dict[str, Any] = {}

    def write(self, page: str, path: str, filters: dict[str, Any], data: Any) -> None:
        envelope = {
            "schema": SCHEMA,
            "view": page,
            "filters": filters,
            "source": {
                "snapshot_commit": self.manifest["validated_commit"],
                "validated_on": self.manifest["validated_on"],
                "tables": list(PAGES[page].tables)
                if page in PAGES
                else sorted(self.manifest["tables"]),
            },
            "data": data,
        }
        target = self.out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_dump(envelope) + "\n", encoding="utf-8", newline="\n")

    def expect(self, key: str, figures: list[dict[str, Any]]) -> None:
        """Parity: every headline figure's display string, in page order, by page and filters."""
        self.parity[key] = [{"key": f["key"], "display": f["display"]} for f in figures]


HOUR_COLUMNS = (
    "service_hour",
    "events",
    "on_time",
    "on_time_share",
    "ci_low",
    "ci_high",
    "late",
    "early",
    "p50_delay_s",
    "p90_delay_s",
    "sufficient",
)


def _compact_stops(stops: list[dict[str, Any]]) -> dict[str, Any]:
    """A route's stops for the site, column-oriented (about 20,000 stops in 300+ files).

    Same values as views.route_stop_details; only the layout changes: hour rows are arrays in
    HOUR_COLUMNS order, and figure labels and help texts are listed once per file.
    """
    figures = stops[0]["figures"] if stops else []
    return {
        "hour_columns": list(HOUR_COLUMNS),
        "figures": [{k: f[k] for k in ("key", "label", "help")} for f in figures],
        "stops": [
            {
                "direction_id": s["direction_id"],
                "stop_id": s["stop_id"],
                "stop_name": s["stop_name"],
                "label": s["label"],
                "values": {f["key"]: f["value"] for f in s["figures"]},
                "display": {f["key"]: f["display"] for f in s["figures"]},
                "hours": [[h[c] for c in HOUR_COLUMNS] for h in s["hours"]],
            }
            for s in stops
        ],
    }


MAP_COLUMNS = (
    "stop_id",
    "label",
    "lat",
    "lon",
    "events",
    "on_time_share",
    "display",
    "sufficient",
    "route_id",
    "direction_id",
)


def _compact_map(view: dict[str, Any]) -> dict[str, Any]:
    """views.stop_map for the site, column-oriented (about 20,000 stops per mode), same order."""
    return {
        "columns": list(MAP_COLUMNS),
        "stops": [[s[c] for c in MAP_COLUMNS] for s in view["stops"]],
        "worst": [s["stop_id"] for s in view["worst"]],
        "sufficient": view["sufficient"],
        "min_events": view["min_events"],
        "summary": view["summary"],
    }


def _meta(manifest: dict[str, Any], days: list[str]) -> dict[str, Any]:
    """Site-wide facts: provenance of the snapshot, the filters, and where each page lives."""
    return {
        "schema": SCHEMA,
        "snapshot": {
            "validated_commit": manifest["validated_commit"],
            "validated_on": manifest["validated_on"],
            "validation": manifest["validation"],
            "tables": manifest["tables"],
            "evidence": manifest["evidence"],
        },
        "modes": [
            {"key": m, "label": views.GROUPS[m], "short": views.SHORT_GROUPS[m]} for m in MODES
        ],
        "days": [{"key": d, "label": day_label(d)} for d in days],
        "pages": {
            name: {"streamlit": p.streamlit, "route": p.route, "tables": list(p.tables)}
            for name, p in PAGES.items()
        },
        "repository": "https://github.com/Lorcelmao/transitometer",
    }


def build(snapshot_dir: Path, out: Path, evidence_out: Path) -> dict[str, Any]:
    """Write every view of the snapshot into `out`; return the parity expectations."""
    manifest = snapshot.load_manifest(snapshot_dir)
    if manifest is None:
        raise ExportError(f"no snapshot in {snapshot_dir}: run `python tasks.py snapshot`")
    if not manifest["validation"].get("ok") or manifest["source"]["kind"] != "spark-gold":
        raise ExportError("the snapshot is not a validated Spark Gold run; refusing to publish it")
    src = kpis.Source("snapshot", str(snapshot_dir))
    folder = snapshot_dir / "evidence"
    days = manifest["service_dates"]
    writer = _Writer(out, manifest)
    with kpis.connect(src) as con:
        writer.write("meta", "meta.json", {}, _meta(manifest, days))
        overview = {}
        for grp in MODES:
            for day in days:
                view = views.overview(con, src, grp, day)
                overview[f"{grp}/{day}"] = view
                writer.expect(f"overview/{grp}/{day}", view["figures"])
        writer.write(
            "overview", "overview.json", {}, {"views": overview, "trust": views.trust(folder)}
        )

        per_day: dict[str, Callable[[Any, kpis.Source, str, str], dict[str, Any]]] = {
            "on-time": views.on_time,
            "headways": views.headways,
            "missing-trips": views.missing_trips,
            "delay": views.delay,
        }
        for page, view_fn in per_day.items():
            for grp in MODES:
                for day in days:
                    view = view_fn(con, src, grp, day)
                    writer.write(page, f"{page}/{grp}-{day}.json", {"mode": grp, "day": day}, view)
                    if view.get("figures"):
                        writer.expect(f"{page}/{grp}/{day}", view["figures"])

        for grp in MODES:
            filters = {"mode": grp}
            writer.write(
                "delay", f"delay/{grp}-segments.json", filters, views.costly_segments(con, src, grp)
            )
            cards = views.route_scorecards(con, src, grp)
            writer.write("scorecards", f"scorecards/{grp}.json", filters, cards)
            writer.parity[f"scorecards/{grp}"] = {
                "least": cards["least"][0]["route_id"] if cards["least"] else None,
                "most": cards["most"][0]["route_id"] if cards["most"] else None,
                "ranked": str(len(cards["ranked"])),
            }
            stop_map = views.stop_map(con, src, grp)
            writer.write("map", f"map/{grp}.json", filters, _compact_map(stop_map))
            writer.parity[f"map/{grp}"] = {
                "worst": stop_map["worst"][0]["label"] if stop_map["worst"] else None,
                "display": stop_map["worst"][0]["display"] if stop_map["worst"] else None,
                "located": str(len(stop_map["stops"])),
            }
            warning = views.early_warning(con, src, grp)
            writer.write("early-warning", f"early-warning/{grp}.json", filters, warning)
            writer.parity[f"early-warning/{grp}"] = {
                v["outcome"]: v.get("verdict", "not measured") for v in warning["verdicts"]
            }
            routes = views.stop_routes(con, src, grp)
            index = []
            for route in routes:
                stops = views.route_stop_details(con, src, grp, route)
                name = route_file(route)
                index.append({"route_id": route, "file": f"{name}.json", "stops": len(stops)})
                writer.write(
                    "stops",
                    f"stops/{grp}/{name}.json",
                    {"mode": grp, "route": route},
                    _compact_stops(stops),
                )
                if route == routes[0] and stops:  # parity sample: the first stop of the first route
                    writer.expect(f"stops/{grp}/{route}/{stops[0]['stop_id']}", stops[0]["figures"])
            writer.write(
                "stops",
                f"stops/{grp}/index.json",
                filters,
                {
                    "routes": index,
                    "min_cell_events": views.MIN_CELL_EVENTS,
                    "definitions": views.STOP_DEFINITIONS,
                },
            )

        feed = {day: views.feed_health(con, src, day) for day in views.feed_days(con, src)}
        writer.write("feed-health", "feed-health.json", {}, {"views": feed})
        for day, view in feed.items():
            writer.parity[f"feed-health/{day}"] = {f["feed"]: f["display"] for f in view["feeds"]}

        validation = views.validation(folder)
        writer.write("validation", "validation.json", {}, validation)
        trust = views.trust(folder)
        writer.parity["validation"] = {
            "parity": trust["parity"]["display"],
            "archive_rows": trust["integrity"]["archive_rows_display"],
            "tests": (
                f"{validation['tests']['passed']:,} / {validation['tests']['total']:,}"
                if validation["tests"]["available"]
                else "not yet measured"
            ),
        }

    evidence_out.mkdir(parents=True, exist_ok=True)
    for name in sorted(manifest["evidence"]):
        shutil.copyfile(folder / name, evidence_out / name)
    return writer.parity


def _replace_contents(target: Path, source: Path) -> None:
    """Make `target` hold exactly `source`'s files (generated output: nothing older survives).

    Empties the folder rather than deleting it, so an open shell or editor in it does not block.
    """
    target.mkdir(parents=True, exist_ok=True)
    for child in target.iterdir():
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    shutil.copytree(source, target, dirs_exist_ok=True)


def _files(root: Path) -> dict[str, Path]:
    return {p.relative_to(root).as_posix(): p for p in sorted(root.rglob("*")) if p.is_file()}


def export(snapshot_dir: Path = kpis.SNAPSHOT_DIR) -> dict[str, Any]:
    """Regenerate web/public/data, web/public/evidence and the parity file; return a summary."""
    with tempfile.TemporaryDirectory() as tmp:
        data, evidence = Path(tmp) / "data", Path(tmp) / "evidence"
        parity = build(snapshot_dir, data, evidence)
        for target, source in ((WEB_DATA, data), (WEB_EVIDENCE, evidence)):
            _replace_contents(target, source)
    PARITY.parent.mkdir(parents=True, exist_ok=True)
    PARITY.write_text(
        json.dumps(parity, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    files = _files(WEB_DATA)
    return {"files": len(files), "bytes": sum(p.stat().st_size for p in files.values())}


def check(snapshot_dir: Path = kpis.SNAPSHOT_DIR) -> list[str]:
    """Paths whose committed content differs from a fresh regeneration (empty = up to date)."""
    with tempfile.TemporaryDirectory() as tmp:
        data, evidence = Path(tmp) / "data", Path(tmp) / "evidence"
        parity = build(snapshot_dir, data, evidence)
        (Path(tmp) / "parity.json").write_text(
            json.dumps(parity, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        problems = []
        for committed, fresh, label in (
            (WEB_DATA, data, "web/public/data"),
            (WEB_EVIDENCE, evidence, "web/public/evidence"),
        ):
            old, new = _files(committed) if committed.exists() else {}, _files(fresh)
            for name in sorted(old.keys() | new.keys()):
                if (
                    name not in old
                    or name not in new
                    or not filecmp.cmp(old[name], new[name], shallow=False)
                ):
                    problems.append(f"{label}/{name}")
        if not PARITY.exists() or not filecmp.cmp(PARITY, Path(tmp) / "parity.json", shallow=False):
            problems.append("showcase/contract/parity-expected.json")
    return problems
