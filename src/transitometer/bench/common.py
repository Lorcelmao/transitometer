"""Host-side helpers shared by the benchmark harnesses (docs/benchmark-fairness.md).

`Host` wraps the compose command of tasks.py: it starts and stops services, runs a command in a
container and parses the JSON line it prints, records which containers are running (the
idle-host check), and drops the Docker VM page cache before a cold run.
"""

from __future__ import annotations

import csv
import json
import subprocess
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT = "transitometer"  # compose project name (docker/compose.yaml)
CONTRACT = "docs/benchmark-fairness.md"


class BenchError(RuntimeError):
    pass


def container(service: str) -> str:
    return f"{PROJECT}-{service}-1"


@dataclass
class Host:
    compose: Callable[..., list[str]]  # tasks.compose_cmd
    root: Path
    spark_image: str

    def run(self, *args: str) -> None:
        code = subprocess.call(self.compose(*args), cwd=self.root, stdout=subprocess.DEVNULL)
        if code:
            raise BenchError(f"docker compose {' '.join(args)} exited with {code}")

    def only(self, *services: str, wait: bool = True) -> None:
        """Run exactly these compose services; stop every other one."""
        running = self.running()
        others = [
            name.removeprefix(f"{PROJECT}-").removesuffix("-1")
            for name in running
            if name.startswith(f"{PROJECT}-")
        ]
        stop = [s for s in others if s not in services]
        if stop:
            self.run("--profile", "*", "stop", *stop)
        self.run(
            "--profile", "*", "up", "-d", "--no-deps", *(["--wait"] if wait else []), *services
        )

    def exec_json(self, service: str, *command: str) -> dict[str, Any]:
        """Run a command in a service container; return the last JSON line it printed."""
        done = subprocess.run(
            self.compose("exec", "-T", service, *command),
            cwd=self.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        lines = [line for line in done.stdout.splitlines() if line.startswith("{")]
        if done.returncode or not lines:
            tail = (done.stderr[-3000:] + "\n" + done.stdout[-3000:]).strip()
            raise BenchError(f"{' '.join(command[:3])} failed ({done.returncode}):\n{tail}")
        result: dict[str, Any] = json.loads(lines[-1])
        return result

    def running(self) -> list[str]:
        out = subprocess.check_output(["docker", "ps", "--format", "{{.Names}}"], text=True)
        return sorted(line for line in out.splitlines() if line)

    def require_only(self, *services: str) -> list[str]:
        """The idle-host check: nothing but these services may run. Returns what runs."""
        running = self.running()
        allowed = {container(s) for s in services}
        extra = [name for name in running if name not in allowed]
        if extra:
            raise BenchError(f"idle-host check failed: unexpected containers {extra}")
        return running

    def drop_caches(self) -> None:
        """Drop the Docker VM page cache (equal for every arm before a cold run)."""
        code = subprocess.call(
            [
                "docker", "run", "--rm", "--privileged", "--user", "root", "--entrypoint", "sh",
                "--pull", "never", self.spark_image,
                "-c", "sync && echo 3 > /proc/sys/vm/drop_caches",
            ],
            stdout=subprocess.DEVNULL,
        )  # fmt: skip
        if code:
            raise BenchError("could not drop the page cache")
        time.sleep(1)


def contract_commit(root: Path) -> str:
    """The commit that last changed the fairness contract (recorded in every run)."""
    out = subprocess.check_output(
        ["git", "log", "-1", "--format=%h", "--", CONTRACT], cwd=root, text=True
    ).strip()
    if not out:
        raise BenchError(f"{CONTRACT} is not committed; commit the contract before measuring")
    return out


def write_csv(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    """Write rows (dicts with the same keys) as CSV; returns the row count."""
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        if rows:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    return len(rows)


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")
