"""Walking skeleton (IMPLEMENTATION_PLAN.md S2): one real hour end to end, plus storage calibration.

landing (read-only mount) -> replay (protobuf, one message per entity) -> Kafka -> Spark
Structured Streaming (availableNow) -> Silver Delta -> DuckDB. Acceptance is asserted on counts;
measurements are written to results/storage-calibration.json.
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from transitometer.ops import storage_check

GB = 10**9
TOPIC = "skeleton.vehiclepositions"
TABLE = "/data/lakehouse/silver/skeleton_vehicle_positions"
CHECKPOINT = "/data/checkpoints/skeleton_vehicle_positions"
HOUR = ("2026-09-22T14:00:00Z", "2026-09-22T15:00:00Z")  # 10:00-11:00 New York, a Tuesday
VP_FILE = "/data/landing/realtime/vehicle_positions/date=2026-09-22/feed=mta_bus/data.parquet"
PROBE_FILE = "/data/landing/realtime/trip_updates/date=2026-09-22/feed=mta_bus/data.parquet"
PROBE_COPY = "/data/scratch/read-probe.parquet"
SPARK_SUBMIT = ["/opt/spark/bin/spark-submit", "--master", "local[8]", "--driver-memory", "6g"]
SRC = "/opt/transitometer/src/transitometer"

Compose = Callable[..., list[str]]


@dataclass
class Outcome:
    checks: dict[str, bool] = field(default_factory=dict)
    measurements: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(self.checks.values())


def _run(cmd: Sequence[str], log: Callable[[str], None]) -> str:
    log("$ " + " ".join(cmd[-6:]))
    done = subprocess.run(list(cmd), capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise RuntimeError(f"command failed ({done.returncode}): {done.stderr[-2000:]}")
    return done.stdout


def _last_json(output: str) -> dict[str, Any]:
    for line in reversed(output.strip().splitlines()):
        if line.startswith("{"):
            parsed: dict[str, Any] = json.loads(line)
            return parsed
    raise RuntimeError(f"no JSON result in output: {output[-500:]}")


def _exec(compose: Compose, service: str, *args: str) -> list[str]:
    return compose("exec", "-T", service, *args)


def reset(compose: Compose, log: Callable[[str], None]) -> None:
    """Remove only the skeleton's own topic, table and checkpoint so every run starts clean."""
    kafka_topics = ["/opt/kafka/bin/kafka-topics.sh", "--bootstrap-server", "localhost:9092"]
    _run(_exec(compose, "kafka", *kafka_topics, "--delete", "--if-exists", "--topic", TOPIC), log)
    for _ in range(30):  # topic deletion is asynchronous
        listed = _run(_exec(compose, "kafka", *kafka_topics, "--list"), log)
        if TOPIC not in listed.split():
            break
        time.sleep(1)
    _run(_exec(compose, "spark", "rm", "-rf", TABLE, CHECKPOINT, PROBE_COPY), log)


def _du(compose: Compose, service: str, path: str, log: Callable[[str], None]) -> int:
    out = _run(_exec(compose, service, "du", "-sk", path), log)
    return int(out.split()[0]) * 1024


def _image_bytes(ref: str, log: Callable[[str], None]) -> int:
    return int(_run(["docker", "image", "inspect", "--format", "{{.Size}}", ref], log).strip())


def run(
    compose: Compose, images: dict[str, str], vhdx: Path | None, log: Callable[[str], None]
) -> Outcome:
    outcome = Outcome()
    checks, m = outcome.checks, outcome.measurements
    reset(compose, log)

    start, end = HOUR
    produced = _last_json(
        _run(
            _exec(
                compose,
                "spark",
                "python3",
                "-m",
                "transitometer.replay.produce",
                "--parquet",
                VP_FILE,
                "--start",
                start,
                "--end",
                end,
                "--topic",
                TOPIC,
            ),
            log,
        )
    )
    job = [
        *SPARK_SUBMIT,
        f"{SRC}/pipeline/skeleton_silver.py",
        "--topic",
        TOPIC,
        "--table",
        TABLE,
        "--checkpoint",
        CHECKPOINT,
    ]
    first = _last_json(_run(_exec(compose, "spark", *job), log))
    second = _last_json(_run(_exec(compose, "spark", *job), log))
    served = _last_json(
        _run(_exec(compose, "spark", "python3", "-m", "transitometer.serve.lakehouse", TABLE), log)
    )
    m["hour_utc"] = {"start": start, "end": end}
    m["replay"], m["spark_first_run"], m["spark_rerun"], m["duckdb"] = (
        produced,
        first,
        second,
        served,
    )

    # Acknowledged by the broker, not merely handed to the client.
    checks["kafka_messages_equal_landing_rows"] = produced["acknowledged"] == produced["rows"] > 0
    checks["silver_rows_equal_kafka_messages"] = first["rows_appended"] == produced["acknowledged"]
    checks["rerun_appends_nothing"] = second["rows_appended"] == 0
    checks["duckdb_equals_silver"] = served["rows"] == first["rows_after"]

    # Storage calibration (§4.2): measured footprints of this run.
    # `docker image inspect` reports content size; the on-disk footprint is added below.
    m["bytes"] = {
        f"image_content_{name}": _image_bytes(ref, log) for name, ref in images.items()
    } | {
        "kafka_log": _du(compose, "kafka", "/var/lib/kafka/data", log),
        "silver_delta_hour": _du(compose, "spark", TABLE, log),
        "checkpoint": _du(compose, "spark", CHECKPOINT, log),
    }

    # Mount-read share: same full scan from the Windows mount vs a Docker-volume copy (min of 2).
    # Both sides can be served from the OS page cache after the first run, so the share is a
    # lower bound on mount overhead; every run is recorded so the spread stays visible.
    all_runs: dict[str, list[float]] = {}

    def probe(path: str) -> float:
        runs = [
            _last_json(
                _run(
                    _exec(compose, "spark", *SPARK_SUBMIT, f"{SRC}/pipeline/read_probe.py", path),
                    log,
                )
            )["seconds"]
            for _ in range(2)
        ]
        all_runs[path] = runs
        return float(min(runs))

    mount_s = probe(PROBE_FILE)
    _run(_exec(compose, "spark", "cp", PROBE_FILE, PROBE_COPY), log)
    volume_s = probe(PROBE_COPY)
    _run(_exec(compose, "spark", "rm", "-f", PROBE_COPY), log)
    share = max(0.0, (mount_s - volume_s) / mount_s) if mount_s else 0.0
    m["mount_read_probe"] = {
        "file": PROBE_FILE,
        "mount_seconds": mount_s,
        "volume_seconds": volume_s,
        "mount_overhead_share": round(share, 3),
        "runs_seconds": all_runs,
        "note": "lower bound: page-cache effects are not controlled; re-measure cold in S10",
        "stage_scale_runs_in_docker": share > 0.2,
    }

    report = storage_check.measure(vhdx, storage_check.Thresholds())
    m["docker_logical_bytes"] = report.logical_bytes
    m["docker_by_type"] = report.usage_by_type
    # containerd keeps compressed blobs + unpacked snapshots: on-disk image size is what counts.
    m["bytes"]["images_on_disk"] = report.usage_by_type.get("Images", 0)
    m["disk_image_bytes"] = report.vhdx_bytes
    m["projection_gb"] = project(m["bytes"])
    checks["projected_steady_within_25gb"] = m["projection_gb"]["steady_total"] <= 25
    return outcome


def project(measured: dict[str, int]) -> dict[str, float]:
    """Steady-state Docker projection (§4.2) from measured parts; Silver scaled from one hour.

    Vehicle-position Silver is scaled to 7 service days (x 24 x 7); trip-update-derived Silver
    (stop events, sampled predictions) is not built yet, so it is budgeted at 3x that figure.
    """
    images = measured["images_on_disk"] / GB
    vp_silver_7d = measured["silver_delta_hour"] * 24 * 7 / GB
    parts = {
        "images": round(images, 2),
        "build_cache_cap": 2.0,
        "kafka_cap": 3.0,
        "silver_vehicle_positions_7d": round(vp_silver_7d, 2),
        "silver_trip_update_derived_budget": round(3 * vp_silver_7d, 2),
        "checkpoints_cap": 1.0,
    }
    parts["steady_total"] = round(sum(parts.values()), 2)
    return parts


def write_report(outcome: Outcome, path: Path) -> None:
    body = {"ok": outcome.ok, "checks": outcome.checks, "measurements": outcome.measurements}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8", newline="\n")
