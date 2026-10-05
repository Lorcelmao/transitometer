"""Cross-platform task runner for Transitometer (stdlib only): `python tasks.py <task>`.

Replaces a Makefile so every team member runs the same commands on Windows, macOS and Linux.
Engine-starting tasks run the soft storage guard first (PROJECT_PLAN.md Â§1.3).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from transitometer.ops import storage_check, versions_lock  # noqa: E402
from transitometer.ops.envfile import read_env_file  # noqa: E402

COMPOSE_FILE = ROOT / "docker" / "compose.yaml"
VERSIONS_FILE = ROOT / "docker" / "versions.env"
SOURCES_FILE = ROOT / "config" / "sources.json"
MANIFEST_FILE = ROOT / "data-manifest.json"
LANDING_REPORT = ROOT / "results" / "landing-volume-report.json"
PROFILES = ("spark", "app", "flink", "clickhouse")


def run(cmd: Sequence[str]) -> int:
    print("$", " ".join(cmd), flush=True)
    return subprocess.call(list(cmd), cwd=ROOT)


def host_config_file() -> Path:
    """config/.env when present, otherwise the committed template."""
    local = ROOT / "config" / ".env"
    return local if local.exists() else ROOT / "config" / ".env.example"


def host_settings() -> dict[str, str]:
    """Host config values, overridable by real environment variables."""
    values = read_env_file(host_config_file())
    return {key: os.environ.get(key, value) for key, value in values.items()}


def compose_cmd(*args: str) -> list[str]:
    # Later env files win: the version lock goes last so host config cannot override pins.
    return [
        "docker",
        "compose",
        "-f",
        str(COMPOSE_FILE),
        "--env-file",
        str(host_config_file()),
        "--env-file",
        str(VERSIONS_FILE),
        *args,
    ]


def thresholds(settings: dict[str, str]) -> storage_check.Thresholds:
    return storage_check.Thresholds(
        warn_gb=float(settings.get("TRANSITOMETER_STORAGE_WARN_GB", "30")),
        block_gb=float(settings.get("TRANSITOMETER_STORAGE_BLOCK_GB", "35")),
    )


def measure_storage() -> tuple[storage_check.StorageReport, storage_check.Thresholds]:
    settings = host_settings()
    limits = thresholds(settings)
    vhdx = settings.get("TRANSITOMETER_DOCKER_VHDX") or None
    report = storage_check.measure(Path(vhdx) if vhdx else None, limits)
    return report, limits


# --- tasks -----------------------------------------------------------------------------------


# Dev tools run through the current interpreter so tasks work without activating the venv.
def task_lint(_: argparse.Namespace) -> int:
    ruff = [sys.executable, "-m", "ruff"]
    return run([*ruff, "check", "."]) or run([*ruff, "format", "--check", "."])


def task_typecheck(_: argparse.Namespace) -> int:
    return run([sys.executable, "-m", "mypy"])


TEST_SUMMARY = ROOT / "results" / "test-summary.json"


def task_test(args: argparse.Namespace) -> int:
    """pytest; with --record, also write the counts to results/test-summary.json (evidence)."""
    if not getattr(args, "record", False):
        return run([sys.executable, "-m", "pytest"])
    import tempfile
    import xml.etree.ElementTree as ElementTree

    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "pytest.xml"
        code = run([sys.executable, "-m", "pytest", f"--junitxml={report}"])
        root = ElementTree.parse(report).getroot()
    suite = root.find("testsuite") if root.tag == "testsuites" else root
    if suite is None:
        print("error: pytest wrote no test suite")
        return 1
    counts = {k: int(suite.get(k, "0")) for k in ("tests", "failures", "errors", "skipped")}
    body = {
        "command": "python tasks.py test",
        "total": counts["tests"],
        "passed": counts["tests"] - counts["failures"] - counts["errors"] - counts["skipped"],
        "failed": counts["failures"] + counts["errors"],
        "skipped": counts["skipped"],
        "ok": code == 0,
    }
    TEST_SUMMARY.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"test summary: {body['passed']}/{body['total']} passed -> {TEST_SUMMARY}")
    return code


def task_check(args: argparse.Namespace) -> int:
    return task_lint(args) or task_typecheck(args) or task_test(args)


def task_compose_config(_: argparse.Namespace) -> int:
    """Validate the compose file for the default services and every profile (no daemon needed)."""
    for profile in (None, *PROFILES):
        extra = ["--profile", profile] if profile else []
        code = run(compose_cmd(*extra, "config", "-q"))
        if code:
            return code
    print("compose config OK for: kafka (default), " + ", ".join(PROFILES))
    return 0


def task_verify_lock(_: argparse.Namespace) -> int:
    images = versions_lock.pinned_images(read_env_file(VERSIONS_FILE))
    problems = versions_lock.verify(images)
    for image in images:
        print(f"{image.key:<18} {image.tag_ref}")
    if problems:
        print("\n".join(["Lock mismatch:", *problems]))
        return 1
    print(f"All {len(images)} pinned images match the registry.")
    return 0


def task_storage_check(args: argparse.Namespace) -> int:
    report, limits = measure_storage()
    print(storage_check.format_report(report, limits))
    if report.status is storage_check.Status.BLOCK and not args.allow_peak:
        print(
            "Refusing: Docker usage is above the block threshold. Clean up the finished phase "
            "(IMPLEMENTATION_PLAN.md Â§4.5) or pass --allow-peak during a scheduled peak."
        )
        return 2
    return 0


def task_storage_report(_: argparse.Namespace) -> int:
    report, limits = measure_storage()
    print(storage_check.format_report(report, limits))
    log_path = Path(host_settings()["TRANSITOMETER_DATA_ROOT"]) / "results" / "storage-log.csv"
    storage_check.append_log(report, log_path)
    print(f"Appended to {log_path}")
    return 0


def task_build(args: argparse.Namespace) -> int:
    """Build the Spark tooling image (Spark, Delta, Kafka connector, DuckDB, Streamlit)."""
    guard = task_storage_check(args)
    if guard:
        return guard
    return run(compose_cmd("--profile", "spark", "build", "spark"))


def task_up(args: argparse.Namespace) -> int:
    guard = task_storage_check(args)
    if guard:
        return guard
    extra = [] if args.profile == "kafka" else ["--profile", args.profile]
    return run(compose_cmd(*extra, "up", "-d"))


def landing_dir() -> Path:
    return Path(host_settings()["TRANSITOMETER_DATA_ROOT"]) / "landing"


def task_fetch(args: argparse.Namespace) -> int:
    """Download the pinned sources into the landing zone and update data-manifest.json."""
    from transitometer.ingest.fetch import fetch_all
    from transitometer.ingest.sources import load_sources

    specs = load_sources(SOURCES_FILE).files()
    if args.only:
        specs = [s for s in specs if s.kind == args.only]
    landing = landing_dir()
    print(f"{len(specs)} files -> {landing}")
    result = fetch_all(
        specs, landing, MANIFEST_FILE, workers=args.workers, accept_changes=args.accept_changes
    )
    print(
        f"downloaded {len(result.downloaded)}, unchanged {len(result.skipped)}, "
        f"failed {len(result.errors)}"
    )
    for relpath, error in sorted(result.errors.items()):
        print(f"  {relpath}: {error}")
    return 0 if result.ok else 1


def task_validate_landing(_: argparse.Namespace) -> int:
    """Validate the landing zone and write results/landing-volume-report.json."""
    import json

    from transitometer.ingest.fetch import load_manifest
    from transitometer.ingest.sources import load_sources
    from transitometer.ingest.validate import summary, validate

    sources = load_sources(SOURCES_FILE)
    report = validate(sources, landing_dir(), load_manifest(MANIFEST_FILE))
    body = summary(report, (sources.window.start, sources.window.end))
    LANDING_REPORT.parent.mkdir(parents=True, exist_ok=True)
    LANDING_REPORT.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    print(f"totals: {body['totals']}")
    for match in body["trip_matching"]:
        print(f"trip_id match {match['feed']}/{match['feed_type']}: {match['match_ratio']:.1%}")
    for line in body["failures"]:
        print(f"FAIL {line}")
    for line in body["warnings"]:
        print(f"WARN {line}")
    print(f"{'OK' if report.ok else 'FAILED'} -> {LANDING_REPORT}")
    return 0 if report.ok else 1


def task_golden(_: argparse.Namespace) -> int:
    """Golden reference KPIs (DuckDB SQL on landing) for the golden window."""
    import duckdb

    from transitometer.golden import runner, suite
    from transitometer.ingest.sources import load_sources

    started = time.perf_counter()
    result = runner.run(
        load_sources(SOURCES_FILE),
        landing_dir(),
        Path(host_settings()["TRANSITOMETER_DATA_ROOT"]) / "golden",
        log=lambda message: print(message, flush=True),  # visible progress when redirected
    )
    runner.write_repo_artifacts(result, ROOT / "golden")
    answers = suite.run(result.out_dir, ROOT / "golden" / "queries")
    (ROOT / "golden" / "queries" / "checksums.json").write_text(
        json.dumps(answers, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    timing = {
        "engine": f"DuckDB {duckdb.__version__}",
        "elapsed_s": round(time.perf_counter() - started, 1),
        "step_seconds": result.step_seconds,
    }
    (ROOT / "results" / "golden-run.json").write_text(
        json.dumps(timing, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"row counts: {result.row_counts}")
    print(f"query suite: {len(answers)} answers frozen in golden/queries/")
    for row in result.summary["otp_summary"]:
        print(
            f"OTP {row['grp']:<6} {row['service_date']} {row['scope']:<10} "
            f"on-time {row['on_time_share']:.1%} of {row['events']:,} events"
        )
    for row in result.summary["crosscheck_summary"]:
        print(f"bus VP cross-check {row['service_date']}: {row['agreement_share']:.1%} agree")
    print(f"outputs: {result.out_dir}  ({time.perf_counter() - started:.0f}s)")
    return 0


def task_axis_a_golden(_: argparse.Namespace) -> int:
    """Axis A input (the passage stream) and golden W1/W2; fails unless W2 = golden headways."""
    from transitometer.axis_a import golden as axis_a_golden
    from transitometer.golden import compare
    from transitometer.ingest.sources import load_sources

    started = time.perf_counter()
    out_dir = Path(host_settings()["TRANSITOMETER_DATA_ROOT"]) / "exports" / "axis-a" / "golden"
    result = axis_a_golden.run(
        load_sources(SOURCES_FILE),
        landing_dir(),
        out_dir,
        log=lambda message: print(message, flush=True),
    )
    policy = compare.Policy.load(ROOT / "golden" / "tolerance.json")
    gate = axis_a_golden.completeness_gate(out_dir, _golden_dir(), policy)
    print(f"completeness gate (W2 from passages vs golden headways): {gate.describe()}")
    body = {
        "row_counts": result.row_counts,
        "checksums": result.checksums,
        "step_seconds": result.step_seconds,
        "elapsed_s": round(time.perf_counter() - started, 1),
        "completeness_gate": {"ok": gate.ok, "detail": gate.describe()},
    }
    (ROOT / "results" / "axis-a-golden.json").write_text(
        json.dumps(body, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"row counts: {result.row_counts}; outputs: {out_dir}")
    return 0 if gate.ok else 1


AXIS_A_EXPORTS = "/data/exports/axis-a"  # <data root>/exports/axis-a inside the containers


def _axis_a_dir() -> Path:
    return Path(host_settings()["TRANSITOMETER_DATA_ROOT"]) / "exports" / "axis-a"


def task_axis_a_produce(args: argparse.Namespace) -> int:
    """Produce the Axis A passage stream into Kafka (recreates the topic), then verify it."""
    guard = task_storage_check(args)
    if guard:
        return guard
    record = ROOT / "results" / "axis-a-produce.json"
    arguments = ["produce", "--parquet", f"{AXIS_A_EXPORTS}/golden/passages.parquet", "--fresh"]
    code = _in_spark("transitometer.axis_a.produce", arguments, record)
    return code or task_axis_a_verify(args)


def task_axis_a_verify(_: argparse.Namespace) -> int:
    """Re-read the passage topic: per-partition counts and SHA-256 must equal the record."""
    import shutil

    record = ROOT / "results" / "axis-a-produce.json"
    shutil.copyfile(
        record, _axis_a_dir() / "produce-record.json"
    )  # the container cannot see results/
    arguments = ["verify", "--record", f"{AXIS_A_EXPORTS}/produce-record.json"]
    return _in_spark(
        "transitometer.axis_a.produce", arguments, ROOT / "results" / "axis-a-verify.json"
    )


def task_golden_check(args: argparse.Namespace) -> int:
    """Check result tables against the frozen golden reference (exit 1 on any failure)."""
    from transitometer.golden import harness
    from transitometer.ingest.sources import load_sources

    window = load_sources(SOURCES_FILE).golden_window
    golden_dir = (
        Path(host_settings()["TRANSITOMETER_DATA_ROOT"])
        / "golden"
        / f"{window.start:%Y%m%d}_{window.end:%Y%m%d}"
    )
    actual = Path(args.tables) if args.tables else None
    print(f"checking {actual or golden_dir} against the golden reference", flush=True)
    report = harness.run(golden_dir, ROOT / "golden", actual)
    print("\n".join(report.lines))
    print(f"{report.failures} failure(s)")
    return 1 if report.failures else 0


def task_skeleton(args: argparse.Namespace) -> int:
    """Walking skeleton: one real hour via Kafka -> Spark -> Delta -> DuckDB, plus calibration."""
    from transitometer.ops import skeleton

    guard = task_storage_check(args)
    if guard:
        return guard
    pins = read_env_file(VERSIONS_FILE)
    spark_image = f"transitometer/spark-tools:{pins['SPARK_VERSION']}"
    steps = [
        compose_cmd("--profile", "spark", "build", "spark"),
        ["docker", "builder", "prune", "-f", "--keep-storage", "2GB"],
        compose_cmd("--profile", "spark", "up", "-d", "--wait", "kafka", "spark"),
    ]
    for step in steps:
        code = run(step)
        if code:
            return code
    vhdx = host_settings().get("TRANSITOMETER_DOCKER_VHDX") or None
    report = ROOT / "results" / "storage-calibration.json"
    report.unlink(missing_ok=True)  # never leave an earlier passing report behind a failed run
    try:
        outcome = skeleton.run(
            compose_cmd,
            images={"spark_tools": spark_image, "kafka": pins["KAFKA_IMAGE"]},
            vhdx=Path(vhdx) if vhdx else None,
            log=print,
        )
    except Exception as exc:
        failed = skeleton.Outcome(checks={"completed": False}, measurements={"error": str(exc)})
        skeleton.write_report(failed, report)
        print(f"FAILED: {exc}")
        return 1
    skeleton.write_report(outcome, report)
    for name, passed in outcome.checks.items():
        print(f"{'PASS' if passed else 'FAIL'} {name}")
    print(f"projection: {outcome.measurements['projection_gb']}")
    print(f"mount read: {outcome.measurements['mount_read_probe']}")
    print(f"{'OK' if outcome.ok else 'FAILED'} -> {report}")
    print("View it: python tasks.py up app  ->  http://127.0.0.1:8501")
    return 0 if outcome.ok else 1


def _replay_days(args: argparse.Namespace) -> list[str]:
    """Explicit --days, else the UTC archive days that hold the golden window."""
    if args.days:
        return list(args.days)
    from transitometer.ingest.sources import DateRange, load_sources

    golden = load_sources(SOURCES_FILE).golden_window
    spill = DateRange(
        golden.start, golden.end + timedelta(days=1)
    )  # service days spill past UTC midnight
    return [f"{day:%Y-%m-%d}" for day in spill.days()]


def _in_spark(module: str, arguments: list[str], report: Path, submit: bool = False) -> int:
    """Run a module in the Spark tooling container; keep its JSON result in results/.

    Plain tools run under python3; Spark jobs (submit=True) go through spark-submit, which is
    what puts PySpark and the connector jars on the path.
    """
    code = run(compose_cmd("--profile", "spark", "up", "-d", "--wait", "kafka", "spark"))
    if code:
        return code
    report.unlink(missing_ok=True)  # never leave an earlier report behind a failed run
    started = time.perf_counter()
    if submit:
        from transitometer.ops.skeleton import SPARK_SUBMIT, SRC

        script = f"{SRC}/{module.removeprefix('transitometer.').replace('.', '/')}.py"
        cmd = compose_cmd("exec", "-T", "spark", *SPARK_SUBMIT, script, *arguments)
    else:
        cmd = compose_cmd("exec", "-T", "spark", "python3", "-m", module, *arguments)
    print("$ " + " ".join(cmd[-len(arguments) - 3 :]), flush=True)
    returncode, stdout, stderr = _stream(cmd)
    errors = report.with_suffix(".stderr.log")
    # Full detail, every run. Spark jobs print their Python traceback on stdout.
    errors.write_text(stderr + "\n--- stdout ---\n" + stdout, encoding="utf-8", newline="\n")
    lines = [line for line in stdout.splitlines() if line.startswith("{")]
    if lines:
        result = json.loads(lines[-1])
        result["elapsed_s"] = round(time.perf_counter() - started, 1)  # wall time incl. startup
        report.parent.mkdir(exist_ok=True)
        report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(json.dumps(result, indent=2))
    if returncode:
        print(stderr[:4000])  # the first error; later lines are shutdown noise
        if submit:
            traceback = stdout[stdout.rfind("Traceback") :] if "Traceback" in stdout else ""
            print(traceback[:4000])
        print(f"full error output: {errors}")
        reason = " (killed: out of memory?)" if returncode == 137 else ""
        print(f"FAILED: {module} exited with {returncode}{reason}")
    return returncode


def _stream(cmd: list[str]) -> tuple[int, str, str]:
    """Run a command, echoing its `progress` lines live; return exit code, stdout, stderr."""
    import threading

    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8"
    )
    captured: list[str] = []

    def drain_stdout() -> None:
        # spark-submit merges the Python driver's stderr into stdout, so echo progress here too.
        assert process.stdout is not None
        for line in process.stdout:
            captured.append(line)
            if line.startswith("progress"):
                print(line.rstrip(), flush=True)

    reader = threading.Thread(target=drain_stdout)
    reader.start()
    stderr_lines = []
    assert process.stderr is not None
    for line in process.stderr:
        stderr_lines.append(line)
        if line.startswith("progress"):
            print(line.rstrip(), flush=True)
    reader.join()
    return process.wait(), "".join(captured), "".join(stderr_lines)


def task_replay(args: argparse.Namespace) -> int:
    """Replay archived feeds into Kafka (default: the golden window's UTC archive days)."""
    guard = task_storage_check(args)
    if guard:
        return guard
    arguments = ["--days", *_replay_days(args), "--speed", str(args.speed)]
    arguments += ["--workers", str(args.workers), "--prefix", args.prefix]
    arguments += ["--minutes", str(args.minutes)]
    if args.feeds:
        arguments += ["--feeds", *args.feeds]
    if args.recreate:
        arguments.append("--recreate")
    code = _in_spark("transitometer.replay.run", arguments, _report("replay-report", args.prefix))
    task_storage_report(args)  # the Kafka footprint of the kept replay, for the storage log
    return code


def task_replay_verify(args: argparse.Namespace) -> int:
    """Check the kept replay against the archive: counts, markers, sampled fidelity."""
    arguments = ["--days", *_replay_days(args), "--sample", str(args.sample)]
    arguments += ["--prefix", args.prefix, "--minutes", str(args.minutes)]
    return _in_spark(
        "transitometer.replay.verify", arguments, _report("replay-verification", args.prefix)
    )


def _report(name: str, prefix: str) -> Path:
    """Where a run report goes: committed for the kept replay, scratch for any other prefix."""
    if prefix == "rt":
        return ROOT / "results" / f"{name}.json"
    scratch = ROOT / "results" / "scratch" / prefix
    scratch.mkdir(parents=True, exist_ok=True)
    return scratch / f"{name}.json"


def task_silver(args: argparse.Namespace) -> int:
    """Decode the kept replay into Silver Delta tables (re-runs append only new messages)."""
    arguments = ["--prefix", args.prefix] + (["--feeds", *args.feeds] if args.feeds else [])
    return _in_spark(
        "transitometer.pipeline.silver_ingest",
        arguments,
        _report("silver-ingest", args.prefix),
        submit=True,
    )


SILVER_COMPARED = ("stop_events", "event_status_summary", "trip_match_summary", "ambiguous_summary")


def _golden_service_dates() -> list[str]:
    from transitometer.ingest.sources import load_sources

    return [f"{d:%Y%m%d}" for d in load_sources(SOURCES_FILE).golden_window.days()]


def _golden_dir() -> Path:
    from transitometer.ingest.sources import load_sources

    window = load_sources(SOURCES_FILE).golden_window
    root = Path(host_settings()["TRANSITOMETER_DATA_ROOT"])
    return root / "golden" / f"{window.start:%Y%m%d}_{window.end:%Y%m%d}"


def compare_with_golden(layer: str, prefix: str, tables: tuple[str, ...], report: Path) -> int:
    """Compare exported lakehouse tables with the golden ones under golden/tolerance.json."""
    from transitometer.golden import compare

    policy = compare.Policy.load(ROOT / "golden" / "tolerance.json")
    actual = Path(host_settings()["TRANSITOMETER_DATA_ROOT"]) / "exports" / prefix / layer
    results = {}
    for table in tables:
        diff = compare.compare_table(table, _golden_dir(), actual, policy)
        print(diff.describe(), flush=True)
        results[table] = {"ok": diff.ok, "detail": diff.describe()}
    body = {
        "layer": layer,
        "prefix": prefix,
        "tables": results,
        "ok": all(r["ok"] for r in results.values()),
    }
    report.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"{sum(not r['ok'] for r in results.values())} table(s) differ; report: {report}")
    return 0 if body["ok"] else 1


def task_silver_events(args: argparse.Namespace) -> int:
    """Infer stop events from Silver + the timetable, export them, compare with golden."""
    from transitometer.ingest.sources import load_sources, schedule_dir

    sources = load_sources(SOURCES_FILE)
    dates = args.service_dates or _golden_service_dates()
    arguments = ["--prefix", args.prefix, "--service-dates", *dates]
    for version in sources.schedules:
        arguments += ["--schedule", f"{version.group}=/data/landing/{schedule_dir(version)}"]
    code = _in_spark(
        "transitometer.pipeline.silver_events",
        arguments,
        _report("silver-events", args.prefix),
        submit=True,
    )
    if code:
        return code
    code = _in_spark(
        "transitometer.pipeline.export",
        ["--prefix", args.prefix, "--layer", "silver", "--tables", *SILVER_COMPARED],
        _report("silver-export", args.prefix),
    )
    if code or args.prefix != "rt":
        return code  # only the kept replay covers the golden window
    return compare_with_golden(
        "silver", args.prefix, SILVER_COMPARED, ROOT / "results" / "validation-silver.json"
    )


GOLD_COMPARED = (
    "otp_summary",
    "otp_route_hour",
    "delay_sanity_summary",
    "headways",
    "headway_regularity",
    "headway_summary",
    "terminal_events",
    "terminal_summary",
    "trip_delivery",
    "missing_trip_summary",
    "missing_by_route",
    "position_jumps",
    "feed_quality_metrics",
    "feed_quality_score",
    "route_scorecard",
    "route_hour_scorecard",
    "stop_hour_reliability",
    "segments",
    "trip_delay_attribution",
    "delay_attribution_summary",
    "segment_travel_stats",
    "warning_decisions",
    "early_warning_summary",
)
# Reference tables the app reads that have no golden counterpart: exported, never compared.
GOLD_REFERENCE = ("stop_names", "stop_locations")


def task_gold(args: argparse.Namespace) -> int:
    """Gold KPI tables from Silver stop events, exported and compared with golden."""
    if not getattr(args, "export_only", False):
        dates = args.service_dates or _golden_service_dates()
        code = _in_spark(
            "transitometer.pipeline.gold_kpis",
            ["--prefix", args.prefix, "--service-dates", *dates],
            _report("gold-kpis", args.prefix),
            submit=True,
        )
        if code:
            return code
    code = _in_spark(
        "transitometer.pipeline.export",
        ["--prefix", args.prefix, "--layer", "gold", "--tables", *GOLD_COMPARED, *GOLD_REFERENCE],
        _report("gold-export", args.prefix),
    )
    if code or args.prefix != "rt":
        return code  # only the kept replay covers the golden window
    return compare_with_golden(
        "gold", args.prefix, GOLD_COMPARED, ROOT / "results" / "validation-gold.json"
    )


DEMO_PREFIX = "demo"
DEMO_DAY = "2026-09-22"  # the demo replays this archive day's first hour (UTC)
DEMO_SERVICE_DATES = ["20260921", "20260922"]  # that hour is the evening of 21 Sep in New York


def task_demo(args: argparse.Namespace) -> int:
    """One real hour end to end: replay -> Silver -> stop events -> Gold -> app (~10 min)."""
    silver_args = argparse.Namespace(prefix=DEMO_PREFIX, feeds=None)
    steps: list[tuple[str, Callable[[], int]]] = [
        (
            "replay one real hour into Kafka",
            lambda: task_replay(
                argparse.Namespace(
                    days=[DEMO_DAY],
                    speed=0.0,
                    workers=args.workers,
                    prefix=DEMO_PREFIX,
                    minutes=60.0,
                    feeds=None,
                    recreate=True,
                    allow_peak=args.allow_peak,
                )
            ),
        ),
        ("Silver: decode, deduplicate, dead-letter", lambda: task_silver(silver_args)),
        (
            "Silver: stop events from the timetable",
            lambda: task_silver_events(
                argparse.Namespace(prefix=DEMO_PREFIX, service_dates=DEMO_SERVICE_DATES)
            ),
        ),
        (
            "Gold: on-time performance, headways, missing trips, feed health",
            lambda: task_gold(
                argparse.Namespace(prefix=DEMO_PREFIX, service_dates=DEMO_SERVICE_DATES)
            ),
        ),
    ]
    if args.fresh:
        code = run(
            compose_cmd(
                "--profile",
                "spark",
                "exec",
                "-T",
                "spark",
                "rm",
                "-rf",
                f"/data/lakehouse/scratch/{DEMO_PREFIX}",
                f"/data/checkpoints/scratch/{DEMO_PREFIX}",
            )
        )
        if code:
            return code
    for number, (label, step) in enumerate(steps, start=1):
        print(f"\n== demo step {number}/{len(steps) + 1}: {label}", flush=True)
        code = step()
        if code:
            print(f"demo stopped at step {number}: {label}")
            return code
    print(f"\n== demo step {len(steps) + 1}/{len(steps) + 1}: start the app", flush=True)
    os.environ["TRANSITOMETER_APP_SOURCE"] = "gold"
    os.environ["TRANSITOMETER_PREFIX"] = DEMO_PREFIX
    code = run(compose_cmd("--profile", "app", "up", "-d", "--force-recreate", "app"))
    if not code:
        print("Transitometer is running at http://localhost:8501 (python tasks.py down to stop)")
    return code


def _validated_origin() -> tuple[str, str]:
    """Commit and date that recorded the validated Gold run: the last change to its run report or
    its golden comparison (both are written by `tasks.py gold`)."""
    out = subprocess.check_output(
        [
            "git",
            "log",
            "-1",
            "--format=%H %cs",
            "--",
            "results/gold-kpis.json",
            "results/validation-gold.json",
        ],
        cwd=ROOT,
        text=True,
    ).split()
    if len(out) != 2:
        raise ValueError("results/validation-gold.json is not committed; commit the run first")
    return out[0], out[1]


def task_snapshot(_: argparse.Namespace) -> int:
    """Copy the validated Gold tables the app reads into showcase/data/ (host, no Docker)."""
    from transitometer.serve import kpis, snapshot

    commit, date = _validated_origin()
    exports = Path(host_settings()["TRANSITOMETER_DATA_ROOT"]) / "exports" / "rt" / "gold"
    try:
        manifest = snapshot.build(
            exports,
            ROOT / "results",
            ROOT / "golden" / "tolerance.json",
            kpis.SNAPSHOT_DIR,
            snapshot.Origin(commit, date),
        )
    except snapshot.SnapshotError as exc:
        print(f"snapshot refused: {exc}")
        return 1
    size = sum(t["bytes"] for t in manifest["tables"].values())
    print(
        f"snapshot: {len(manifest['tables'])} tables ({size / 1e6:.1f} MB), "
        f"validated run {commit[:7]} on {date} -> {kpis.SNAPSHOT_DIR}"
    )
    return 0


def task_web_data(args: argparse.Namespace) -> int:
    """JSON for the Next.js site from the validated snapshot (host, no Docker)."""
    from transitometer.serve import web_export

    try:
        if args.check:
            stale = web_export.check()
            if stale:
                print("web data is out of date with the snapshot; run `python tasks.py web-data`:")
                print("\n".join(f"  {path}" for path in stale[:20]))
                return 1
            print("web data matches the snapshot")
            return 0
        summary = web_export.export()
    except web_export.ExportError as exc:
        print(f"web-data refused: {exc}")
        return 1
    print(
        f"web data: {summary['files']} files ({summary['bytes'] / 1e6:.1f} MB) -> web/public/data"
    )
    return 0


def task_down(_: argparse.Namespace) -> int:
    """Stop every service; named volumes are kept (use Docker directly for deliberate resets)."""
    return run(compose_cmd("--profile", "*", "down"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tasks.py", description=__doc__)
    sub = parser.add_subparsers(dest="task", required=True)
    simple = {
        "lint": (task_lint, "ruff lint + format check"),
        "typecheck": (task_typecheck, "mypy (strict)"),
        "compose-config": (task_compose_config, "validate docker/compose.yaml for every profile"),
        "verify-lock": (task_verify_lock, "check pinned image digests against the registry"),
        "storage-report": (
            task_storage_report,
            "print usage and append to results/storage-log.csv",
        ),
        "validate-landing": (task_validate_landing, "validate landing data, write volume report"),
        "golden": (task_golden, "golden reference KPIs (DuckDB) for the golden window"),
        "axis-a-golden": (
            task_axis_a_golden,
            "Axis A passage stream + golden W1/W2 (checked against golden headways)",
        ),
        "snapshot": (task_snapshot, "copy the validated Gold app tables into showcase/data/"),
        "down": (task_down, "stop all services (keeps volumes)"),
    }
    for name, (func, help_text) in simple.items():
        sub.add_parser(name, help=help_text).set_defaults(func=func)

    web = sub.add_parser("web-data", help="JSON for the Next.js site from the snapshot")
    web.add_argument("--check", action="store_true", help="fail if the committed JSON is stale")
    web.set_defaults(func=task_web_data)

    for test_name, test_task, test_help in (
        ("test", task_test, "pytest"),
        ("check", task_check, "lint + typecheck + test"),
    ):
        tests = sub.add_parser(test_name, help=test_help)
        tests.add_argument(
            "--record", action="store_true", help="write results/test-summary.json (evidence)"
        )
        tests.set_defaults(func=test_task)

    check = sub.add_parser("storage-check", help="soft storage guard (exit 2 when blocked)")
    check.add_argument(
        "--allow-peak", action="store_true", help="proceed above the block threshold"
    )
    check.set_defaults(func=task_storage_check)

    fetch = sub.add_parser("fetch", help="download pinned sources into the landing zone")
    fetch.add_argument("--only", choices=("realtime", "schedule"), help="fetch one kind only")
    fetch.add_argument("--workers", type=int, default=4, help="parallel downloads")
    fetch.add_argument(
        "--accept-changes", action="store_true", help="adopt upstream content changes"
    )
    fetch.set_defaults(func=task_fetch)

    gcheck = sub.add_parser(
        "golden-check",
        help="check golden outputs (or --tables DIR of an engine) against the frozen reference",
    )
    gcheck.add_argument("--tables", help="directory of an engine's exported Parquet tables")
    gcheck.set_defaults(func=task_golden_check)

    for name, axis_task, help_text in (
        ("axis-a-produce", task_axis_a_produce, "Axis A passage stream into Kafka, verified"),
        ("axis-a-verify", task_axis_a_verify, "verify the Axis A passage topic against its record"),
    ):
        axis = sub.add_parser(name, help=help_text)
        axis.add_argument(
            "--allow-peak", action="store_true", help="proceed above the block threshold"
        )
        axis.set_defaults(func=axis_task)

    replay = sub.add_parser("replay", help="replay archived feeds into Kafka (kept for engines)")
    replay.add_argument("--days", nargs="+", help="UTC archive days (default: golden window)")
    replay.add_argument("--feeds", nargs="*", help="subset of feeds")
    replay.add_argument("--speed", type=float, default=0.0, help="x real time; 0 = at once")
    replay.add_argument("--workers", type=int, default=5, help="encoders for bus trip updates")
    replay.add_argument("--recreate", action="store_true", help="delete and recreate the topics")
    replay.add_argument("--prefix", default="rt", help="topic prefix (rt = the kept real replay)")
    replay.add_argument("--minutes", type=float, default=0, help="only the first N minutes")
    replay.add_argument(
        "--allow-peak", action="store_true", help="proceed above the block threshold"
    )
    replay.set_defaults(func=task_replay)

    rverify = sub.add_parser("replay-verify", help="check the kept replay against the archive")
    rverify.add_argument("--days", nargs="+", help="UTC archive days (default: golden window)")
    rverify.add_argument("--sample", type=int, default=20, help="snapshots decoded per feed")
    rverify.add_argument("--prefix", default="rt", help="topic prefix of the replay")
    rverify.add_argument("--minutes", type=float, default=0, help="as passed to the replay")
    rverify.set_defaults(func=task_replay_verify)
    silver = sub.add_parser("silver", help="decode the kept replay into Silver Delta tables")
    silver.add_argument("--prefix", default="rt")
    silver.add_argument("--feeds", nargs="*")
    silver.set_defaults(func=task_silver)
    events = sub.add_parser(
        "silver-events", help="stop events from Silver + timetable, compared with golden"
    )
    events.add_argument("--prefix", default="rt")
    events.add_argument("--service-dates", nargs="*", help="YYYYMMDD (default: golden window)")
    events.set_defaults(func=task_silver_events)
    gold = sub.add_parser("gold", help="Gold KPI tables (BR1-BR8), compared with golden")
    gold.add_argument("--prefix", default="rt")
    gold.add_argument("--service-dates", nargs="*", help="YYYYMMDD (default: golden window)")
    gold.add_argument(
        "--export-only", action="store_true", help="re-export and compare without the Spark job"
    )
    gold.set_defaults(func=task_gold)
    demo = sub.add_parser("demo", help="one real hour end to end, then open the app")
    demo.add_argument("--workers", type=int, default=4)
    demo.add_argument("--fresh", action="store_true", help="drop earlier demo tables first")
    demo.add_argument("--allow-peak", action="store_true", help="proceed above the block threshold")
    demo.set_defaults(func=task_demo)

    skel = sub.add_parser("skeleton", help="walking skeleton end to end + storage calibration")
    skel.add_argument("--allow-peak", action="store_true", help="proceed above the block threshold")
    skel.set_defaults(func=task_skeleton)

    up = sub.add_parser("up", help="storage guard, then start kafka or a profile")
    up.add_argument("profile", choices=("kafka", *PROFILES))
    up.add_argument("--allow-peak", action="store_true", help="proceed above the block threshold")
    up.set_defaults(func=task_up)
    image = sub.add_parser("build", help="storage guard, then build the Spark tooling image")
    image.add_argument(
        "--allow-peak", action="store_true", help="proceed above the block threshold"
    )
    image.set_defaults(func=task_build)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result: int = args.func(args)
    except FileNotFoundError as exc:
        print(f"error: required program or file not found: {exc.filename or exc}")
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"error: {' '.join(exc.cmd)} failed (exit {exc.returncode}); is Docker running?")
        return 1
    except ValueError as exc:
        print(f"error: invalid configuration: {exc}")
        return 1
    return result


if __name__ == "__main__":
    sys.exit(main())
