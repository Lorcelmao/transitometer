"""Soft storage guard for the Docker engine zone.

Docker Desktop (WSL2 mode) offers no hard disk-usage limit, so the <= 25 GB budget from
PROJECT_PLAN.md §1.3 is enforced here: engine runs are refused once logical Docker usage
reaches the block threshold. The Docker disk image is non-sparse (it keeps its high-water
size), so its file size is reported separately to signal when compaction is worthwhile.
"""

from __future__ import annotations

import csv
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

# Docker's human-readable sizes (e.g. "1.756GB", "43.86MB", "0B") use decimal units.
_UNITS = {"B": 1, "KB": 10**3, "MB": 10**6, "GB": 10**9, "TB": 10**12}
_SIZE_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([kKMGT]?B)\s*$")

GB = 10**9


class Status(str, Enum):
    OK = "OK"
    WARN = "WARN"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class Thresholds:
    warn_gb: float = 25.0
    block_gb: float = 30.0

    def __post_init__(self) -> None:
        if not 0 < self.warn_gb < self.block_gb:
            raise ValueError("thresholds must satisfy 0 < warn_gb < block_gb")


@dataclass(frozen=True)
class StorageReport:
    usage_by_type: dict[str, int]
    vhdx_bytes: int | None
    status: Status
    compaction_advised: bool

    @property
    def logical_bytes(self) -> int:
        return sum(self.usage_by_type.values())


def parse_size(text: str) -> int:
    """Convert a Docker size string such as '1.756GB' or '0B' into bytes."""
    match = _SIZE_RE.match(text)
    if not match:
        raise ValueError(f"unrecognised size: {text!r}")
    value, unit = match.groups()
    return round(float(value) * _UNITS[unit.upper()])


def parse_system_df(json_lines: str) -> dict[str, int]:
    """Parse `docker system df --format '{{json .}}'` output into bytes per resource type."""
    usage: dict[str, int] = {}
    for line in json_lines.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        usage[row["Type"]] = parse_size(row["Size"])
    return usage


def classify(logical_bytes: int, thresholds: Thresholds) -> Status:
    if logical_bytes >= thresholds.block_gb * GB:
        return Status.BLOCK
    if logical_bytes >= thresholds.warn_gb * GB:
        return Status.WARN
    return Status.OK


def build_report(
    usage_by_type: dict[str, int], vhdx_bytes: int | None, thresholds: Thresholds
) -> StorageReport:
    logical = sum(usage_by_type.values())
    # Non-sparse image: a file well above live usage means deleted data still occupies disk.
    compaction_advised = (
        vhdx_bytes is not None
        and vhdx_bytes >= thresholds.block_gb * GB
        and logical < thresholds.warn_gb * GB
    )
    return StorageReport(
        usage_by_type, vhdx_bytes, classify(logical, thresholds), compaction_advised
    )


def parse_buildx_private(text: str) -> int | None:
    """Private (unshared) bytes from `docker buildx du` summary output, or None if absent.

    With the containerd image store most build-cache records are the image's own layers
    ("Shared"); only the private part occupies disk beyond the images themselves.
    """
    match = re.search(r"^Private:\s*(\S+)\s*$", text, re.MULTILINE)
    return parse_size(match.group(1)) if match else None


def measure(vhdx_path: Path | None, thresholds: Thresholds) -> StorageReport:
    """Query the running Docker engine and the disk image file."""
    result = subprocess.run(
        ["docker", "system", "df", "--format", "{{json .}}"],
        capture_output=True,
        text=True,
        check=True,
    )
    usage = parse_system_df(result.stdout)
    if "Build Cache" in usage:
        # Count only the unshared build cache, so shared image layers are not counted twice.
        cache = subprocess.run(
            ["docker", "buildx", "du"], capture_output=True, text=True, check=False
        )
        private = parse_buildx_private(cache.stdout) if cache.returncode == 0 else None
        if private is not None:
            usage["Build Cache"] = private
    vhdx_bytes = vhdx_path.stat().st_size if vhdx_path and vhdx_path.exists() else None
    return build_report(usage, vhdx_bytes, thresholds)


def format_report(report: StorageReport, thresholds: Thresholds) -> str:
    lines = [f"{kind:<14} {size / GB:8.2f} GB" for kind, size in report.usage_by_type.items()]
    lines.append(f"{'Docker total':<14} {report.logical_bytes / GB:8.2f} GB")
    if report.vhdx_bytes is not None:
        lines.append(f"{'Disk image':<14} {report.vhdx_bytes / GB:8.2f} GB (file on host)")
    lines.append(
        f"Status: {report.status.value} "
        f"(warn >= {thresholds.warn_gb:g} GB, block >= {thresholds.block_gb:g} GB)"
    )
    if report.compaction_advised:
        lines.append(
            "Advice: disk image far above live usage; compact it (IMPLEMENTATION_PLAN.md §4.4)."
        )
    return "\n".join(lines)


def append_log(report: StorageReport, log_path: Path) -> None:
    """Append one row to the storage log (IMPLEMENTATION_PLAN.md §4.5)."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not log_path.exists()
    with log_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if is_new:
            writer.writerow(["timestamp_utc", "type", "bytes"])
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for kind, size in report.usage_by_type.items():
            writer.writerow([stamp, kind, size])
        writer.writerow([stamp, "total", report.logical_bytes])
        if report.vhdx_bytes is not None:
            writer.writerow([stamp, "disk_image", report.vhdx_bytes])
