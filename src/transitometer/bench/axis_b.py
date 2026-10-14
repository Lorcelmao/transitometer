"""Axis B benchmark harness (host): docs/benchmark-fairness.md, section Axis B.

Steps, each writing raw CSVs under results/benchmarks/:
  latency     3 runs, arm order rotated (B1 B2 B3, B2 B3 B1, B3 B1 B2); per run and arm: stop
              everything, drop the page cache, start only the arm, one cold pass of the suite and
              5 warm passes; the cold answers are graded against golden
  freshness   3 runs: Spark commits a new service day to a fresh stop_events copy (B1 times
              the commit and its own first query); then B2 and B3 (rotated) time their first
              answer that includes it (B3 includes its load from Delta)
  footprint   Delta active data and log bytes vs ClickHouse parts (on disk, compressed, raw)
  compaction  OPTIMIZE the Axis B tables, 3 rotated runs of B1 and B2 on the compacted layout,
              VACUUM, 3 runs of the zero-copy sub-arm (B2 via read_parquet), then rebuild the
              Axis B copy so later work sees the S9 layout again
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from transitometer.axis_b import clickhouse, grading
from transitometer.bench.common import Host, contract_commit, now, write_csv
from transitometer.ops.skeleton import SPARK_SUBMIT, SRC

ROTATION = (("B1", "B2", "B3"), ("B2", "B3", "B1"), ("B3", "B1", "B2"))
SERVICE = {"B1": "spark", "B2": "spark", "B2z": "spark", "B3": "clickhouse"}
PASSES = 6  # 1 cold + 5 warm


def _submit(module: str, *args: str) -> list[str]:
    return [*SPARK_SUBMIT, f"{SRC}/{module.replace('.', '/')}.py", *args]


class AxisB:
    def __init__(
        self, host: Host, data_root: Path, golden_tables: Path, log: Callable[[str], None]
    ):
        self.host = host
        self.out = host.root / "results" / "benchmarks"
        self.answers = data_root / "exports" / "axis-b"
        self.golden_tables = golden_tables
        self.contract = contract_commit(host.root)
        self.log = log

    # -- one arm, one run ------------------------------------------------------------------
    def _start(self, service: str) -> list[str]:
        self.host.run("--profile", "*", "stop")
        self.host.drop_caches()
        self.host.run("--profile", "*", "up", "-d", "--no-deps", service)
        if service == "clickhouse":
            clickhouse.wait_ready()
        return self.host.require_only(service)

    def arm(self, arm: str, layout: str) -> tuple[dict[str, Any], list[str]]:
        containers = self._start(SERVICE[arm])
        folder = f"bench-{arm.lower()}"
        if arm == "B1":
            record = self.host.exec_json(
                "spark",
                *_submit("axis_b.spark_arm", "--passes", str(PASSES), "--answers", folder),
            )
        elif arm in ("B2", "B2z"):
            extra = ["--zero-copy"] if arm == "B2z" else []
            record = self.host.exec_json(
                "spark",
                "python3", "-m", "transitometer.axis_b.duckdb_arm",
                "--passes", str(PASSES), "--answers", folder, *extra,
            )  # fmt: skip
        else:
            record = clickhouse.run(self.answers / folder, passes=PASSES)
        return record, containers

    def _runs(self, orders: tuple[tuple[str, ...], ...], layout: str, tag: str) -> None:
        samples: list[dict[str, Any]] = []
        runs: list[dict[str, Any]] = []
        for number, order in enumerate(orders, start=1):
            for position, arm in enumerate(order, start=1):
                self.log(f"axis-b {tag}: run {number}, arm {arm} ({position}/{len(order)})")
                started = now()
                record, containers = self.arm(arm, layout)
                graded = grading.grade(
                    record,
                    self.answers / f"bench-{arm.lower()}",
                    self.host.root / "golden",
                    self.golden_tables,
                )
                runs.append(
                    {
                        "run": number,
                        "position": position,
                        "arm": arm,
                        "layout": layout,
                        "started_at": started,
                        "equal": graded["equal"],
                        "applicable": graded["applicable"],
                        "parity_ok": graded["ok"],
                        "engine_version": record.get("version"),
                        "threads": record.get("threads", record.get("cores")),
                        "containers": " ".join(containers),
                        "contract": self.contract,
                    }
                )
                if not graded["ok"]:
                    bad = [n for n, q in graded["queries"].items() if q.get("ok") is False]
                    self.log(f"  parity FAILED on {bad}")
                for query, times in record["timings"].items():
                    for index, seconds in enumerate(times):
                        samples.append(
                            {
                                "run": number,
                                "arm": arm,
                                "layout": layout,
                                "pass": index + 1,
                                "phase": "cold" if index == 0 else "warm",
                                "query": query,
                                "seconds": seconds,
                            }
                        )
        write_csv(self.out / f"axis_b_{tag}_latency.csv", samples)
        write_csv(self.out / f"axis_b_{tag}_runs.csv", runs)

    # -- steps -------------------------------------------------------------------------------
    def latency(self) -> None:
        self._runs(ROTATION, "delta", "base")

    def freshness(self) -> None:
        rows: list[dict[str, Any]] = []
        for number in range(1, 4):
            self.log(f"axis-b freshness: run {number}")
            containers = self._start("spark")
            b1 = self.host.exec_json("spark", *_submit("bench.axis_b_spark", "freshness"))
            result = b1["result"]
            rows.append(self._fresh_row(number, "B1", result["visible_s"], result, containers))
            for arm in ("B2", "B3") if number % 2 else ("B3", "B2"):
                if arm == "B2":
                    containers = self._start("spark")
                    out = self.host.exec_json(
                        "spark", "python3", "-m", "transitometer.bench.axis_b_local",
                        "freshness-duckdb",
                    )["result"]  # fmt: skip
                else:
                    containers = self._start("clickhouse")
                    out = clickhouse.freshness("rt")
                rows.append(self._fresh_row(number, arm, out["visible_s"], result, containers, out))
        write_csv(self.out / "axis_b_freshness.csv", rows)

    def _fresh_row(
        self,
        number: int,
        arm: str,
        visible_s: float,
        commit: dict[str, Any],
        containers: list[str],
        own: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        own = own or commit
        return {
            "run": number,
            "arm": arm,
            "delta_commit_s": commit["commit_s"],
            "load_s": own.get("load_s", 0.0),
            "visible_s": visible_s,
            "ok": own["ok"],
            "containers": " ".join(containers),
            "contract": self.contract,
        }

    def footprint(self) -> None:
        self._start("spark")
        delta = self.host.exec_json("spark", *_submit("bench.axis_b_spark", "layout"))["result"]
        self._start("clickhouse")
        parts = {p["table"]: p for p in clickhouse.footprint()}
        rows = []
        for table, info in delta.items():
            part = parts.get(table, {})
            rows.append(
                {
                    "table": table,
                    "rows": int(part.get("rows", 0)),
                    "delta_files": info["files"],
                    "delta_data_bytes": info["data_bytes"],
                    "delta_log_bytes": info["log_bytes"],
                    "clickhouse_parts": int(part.get("parts", 0)),
                    "clickhouse_bytes_on_disk": int(part.get("bytes_on_disk", 0)),
                    "clickhouse_compressed_bytes": int(part.get("compressed_bytes", 0)),
                    "clickhouse_uncompressed_bytes": int(part.get("uncompressed_bytes", 0)),
                }
            )
        write_csv(self.out / "axis_b_footprint.csv", rows)

    def compaction(self) -> None:
        self._start("spark")
        optimized = self.host.exec_json("spark", *_submit("bench.axis_b_spark", "optimize"))
        write_csv(
            self.out / "axis_b_compaction.csv",
            [
                {
                    "table": table,
                    "files_before": info["before"]["files"],
                    "files_after": info["after"]["files"],
                    "data_bytes_before": info["before"]["data_bytes"],
                    "data_bytes_after": info["after"]["data_bytes"],
                    "optimize_s": info["optimize_s"],
                }
                for table, info in optimized["result"].items()
            ],
        )
        self._runs((("B1", "B2"), ("B2", "B1"), ("B1", "B2")), "optimized", "optimized")
        self._start("spark")
        vacuumed = self.host.exec_json("spark", *_submit("bench.axis_b_spark", "vacuum"))
        invalid = [t for t, v in vacuumed["result"].items() if not v["zero_copy_valid"]]
        if invalid:
            raise RuntimeError(f"zero-copy precondition failed after VACUUM: {invalid}")
        self._runs((("B2z",), ("B2z",), ("B2z",)), "zero_copy", "zero_copy")
        self.log("axis-b: rebuilding the Axis B copy (OPTIMIZE and VACUUM rewrote it)")
        self._start("spark")
        rebuilt = self.host.exec_json("spark", *_submit("axis_b.delta_load"))
        if not rebuilt["ok"]:
            raise RuntimeError("rebuilding lakehouse/axis_b failed")
        (self.out / "axis_b_rebuild.json").write_text(
            json.dumps({"ok": True, "at": now()}) + "\n", encoding="utf-8"
        )
