"""Cross-platform task runner for Transitometer (stdlib only): `python tasks.py <task>`.

Replaces a Makefile so every team member runs the same commands on Windows, macOS and Linux.
Engine-starting tasks run the soft storage guard first (PROJECT_PLAN.md §1.3).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Sequence
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
        warn_gb=float(settings.get("TRANSITOMETER_STORAGE_WARN_GB", "25")),
        block_gb=float(settings.get("TRANSITOMETER_STORAGE_BLOCK_GB", "30")),
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


def task_test(_: argparse.Namespace) -> int:
    return run([sys.executable, "-m", "pytest"])


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
            "(IMPLEMENTATION_PLAN.md §4.5) or pass --allow-peak during a scheduled peak."
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


def task_down(_: argparse.Namespace) -> int:
    """Stop every service; named volumes are kept (use Docker directly for deliberate resets)."""
    return run(compose_cmd("--profile", "*", "down"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tasks.py", description=__doc__)
    sub = parser.add_subparsers(dest="task", required=True)
    simple = {
        "lint": (task_lint, "ruff lint + format check"),
        "typecheck": (task_typecheck, "mypy (strict)"),
        "test": (task_test, "pytest"),
        "check": (task_check, "lint + typecheck + test"),
        "compose-config": (task_compose_config, "validate docker/compose.yaml for every profile"),
        "verify-lock": (task_verify_lock, "check pinned image digests against the registry"),
        "storage-report": (
            task_storage_report,
            "print usage and append to results/storage-log.csv",
        ),
        "validate-landing": (task_validate_landing, "validate landing data, write volume report"),
        "down": (task_down, "stop all services (keeps volumes)"),
    }
    for name, (func, help_text) in simple.items():
        sub.add_parser(name, help=help_text).set_defaults(func=func)

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

    skel = sub.add_parser("skeleton", help="walking skeleton end to end + storage calibration")
    skel.add_argument("--allow-peak", action="store_true", help="proceed above the block threshold")
    skel.set_defaults(func=task_skeleton)

    up = sub.add_parser("up", help="storage guard, then start kafka or a profile")
    up.add_argument("profile", choices=("kafka", *PROFILES))
    up.add_argument("--allow-peak", action="store_true", help="proceed above the block threshold")
    up.set_defaults(func=task_up)
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
