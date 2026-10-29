"""Real-data scaling harness (host): docs/benchmark-fairness.md, section Real-data scaling.

For each slice of 1, 3 and 7 archive days from 2026-09-17, one at a time:
  1. replay the slice into Kafka once under its own prefix (`scale<days>`), recreating the topics
  2. run the Silver build (`silver_ingest`, all feeds) 3 times; before each run the slice's
     scratch Silver and checkpoints are removed and the page cache is dropped, so every run is
     a cold build of the same input
  3. remove the slice's scratch Silver, checkpoints and topics before the next slice
Only `kafka` and `spark` run. Each run's wall time is measured on the host, and the bytes of
its Silver output and checkpoints are recorded. A subset of slices can run on its own; rows of
the other slices already in the CSV are kept.
"""

from __future__ import annotations

import csv
import json
import time
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from transitometer.bench.common import Host, contract_commit, now, write_csv
from transitometer.ops.skeleton import SPARK_SUBMIT, SRC

FIRST_DAY = date(2026, 9, 17)
SLICES = (1, 3, 7)
RUNS = 3
# Run in the spark container: bytes of one slice's scratch Silver and checkpoints.
SIZES = (
    "import json, os, sys\n"
    "def size(p): return sum(os.path.getsize(os.path.join(d, f)) "
    "for d, _, fs in os.walk(p) for f in fs)\n"
    "p = sys.argv[1]\n"
    "print(json.dumps({'silver_bytes': size(f'/data/lakehouse/scratch/{p}'), "
    "'checkpoint_bytes': size(f'/data/checkpoints/scratch/{p}')}))"
)


def slice_days(days: int) -> list[str]:
    return [(FIRST_DAY + timedelta(days=i)).isoformat() for i in range(days)]


class Scaling:
    def __init__(self, host: Host, guard: Callable[[], int], log: Callable[[str], None]):
        self.host = host
        self.guard = guard  # the storage guard of tasks.py; nonzero = refuse
        self.out = host.root / "results" / "benchmarks"
        self.contract = contract_commit(host.root)
        self.log = log

    def _sh(self, script: str, service: str = "spark") -> None:
        self.host.run("exec", "-T", "-u", "root", service, "sh", "-c", script)

    def _clear(self, prefix: str) -> None:
        self._sh(f"rm -rf /data/lakehouse/scratch/{prefix} /data/checkpoints/scratch/{prefix}")

    def _drop_topics(self, prefix: str) -> None:
        topics = "/opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092"
        self._sh(f"{topics} --delete --if-exists --topic '{prefix}\\..*'", service="kafka")

    def _kept(self, days: tuple[int, ...]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Rows and replay records already written for the slices not being run now."""
        runs, replays = self.out / "scaling_runs.csv", self.out / "scaling_replays.json"
        rows: list[dict[str, Any]] = []
        if runs.exists():
            with runs.open(newline="", encoding="utf-8") as handle:
                rows = [r for r in csv.DictReader(handle) if int(r["days"]) not in days]
        kept = json.loads(replays.read_text("utf-8")) if replays.exists() else []
        return rows, [r for r in kept if r["days"] not in days]

    def run(self, slices: tuple[int, ...] = SLICES) -> None:
        rows, replays = self._kept(slices)
        for days in slices:
            if self.guard():
                raise RuntimeError("storage guard refused the scaling slice")
            prefix = f"scale{days}"
            self.host.run("--profile", "*", "up", "-d", "--wait", "kafka", "spark")
            self.log(f"scaling: replaying {days} day(s) into {prefix}.*")
            started = time.perf_counter()
            replay = self.host.exec_json(
                "spark", "python3", "-m", "transitometer.replay.run",
                "--days", *slice_days(days), "--speed", "0", "--workers", "5",
                "--prefix", prefix, "--minutes", "0", "--recreate",
            )  # fmt: skip
            replays.append(
                {
                    "days": days,
                    "replay_s": round(time.perf_counter() - started, 1),
                    "report": replay,
                }
            )
            for number in range(1, RUNS + 1):
                self._clear(prefix)
                self.host.drop_caches()
                containers = self.host.require_only("kafka", "spark")
                self.log(f"scaling: {days} day(s), Silver build run {number}")
                began = now()
                started = time.perf_counter()
                result = self.host.exec_json(
                    "spark", *SPARK_SUBMIT, f"{SRC}/pipeline/silver_ingest.py", "--prefix", prefix
                )
                seconds = time.perf_counter() - started
                feeds = result["feeds"]
                sizes = self.host.exec_json("spark", "python3", "-c", SIZES, prefix)
                rows.append(
                    {
                        "days": days,
                        "first_day": slice_days(days)[0],
                        "run": number,
                        "seconds": round(seconds, 1),
                        "messages_in": sum(f["messages_in"] for f in feeds),
                        "rows_out": sum(f["rows_out"] for f in feeds),
                        "balanced": all(f["balanced"] for f in feeds),
                        "silver_bytes": sizes["silver_bytes"],
                        "checkpoint_bytes": sizes["checkpoint_bytes"],
                        "started_at": began,
                        "containers": " ".join(containers),
                        "contract": self.contract,
                    }
                )
                rows.sort(key=lambda r: (int(r["days"]), int(r["run"])))
                write_csv(self.out / "scaling_runs.csv", rows)
            self._clear(prefix)
            self._drop_topics(prefix)
            replays.sort(key=lambda r: int(r["days"]))
            (self.out / "scaling_replays.json").write_text(
                json.dumps(replays, indent=2, default=str) + "\n", encoding="utf-8"
            )
