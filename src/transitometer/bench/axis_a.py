"""Axis A benchmark harness (host): docs/benchmark-fairness.md, section Axis A.

One run: prepare the slice (bench.axis_a_slice), recreate the topics, start the engine and wait
until it is ready, send the slice at the target rate (bench.axis_a_kafka produce), wait until the
engine has drained the recorded offsets, dump the input and output topics with their append times
and compute latency and correctness on the host. A recovery run kills the engine with SIGKILL
while the producer is sending and restarts it at once from its checkpoint.

Scenarios (each 3 runs, engine order alternating per run):
  latency   200/s for 300 s
  knee      500, 1000, 2000, 4000/s for 120 s
  late      late:0, late:30, late:120 at 200/s for 120 s
  dup       dup at 200/s for 120 s
  recovery  200/s for 300 s, SIGKILL at 120 s
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from transitometer.bench import axis_a_latency as lat
from transitometer.bench import axis_a_slice
from transitometer.bench.common import BenchError, Host, container, contract_commit, now, write_csv
from transitometer.golden import compare
from transitometer.ops.skeleton import SPARK_SUBMIT, SRC

EXPORTS = "/data/exports/axis-a/bench"  # the same folder inside the containers
FLINK_REST = "http://127.0.0.1:8081"
SERVICES = {
    "spark": ("kafka", "spark"),
    "flink": ("kafka", "spark", "flink-jobmanager", "flink-taskmanager"),
}
OUTPUT_KEYS = {
    "w1": ("grp", "service_date", "route_id", "stop_id", "window_start"),
    "w2": ("grp", "service_date", "route_id", "stop_id", "trip_key"),
}
WARMUP_MS = 30_000
SLO_P95_MS = 30_000
SLO_DRAIN_MS = 60_000


@dataclass(frozen=True)
class Scenario:
    name: str
    rate: int
    duration: int
    plan: str = "clean"
    kill_at: float | None = None

    @property
    def label(self) -> str:
        return f"{self.name}-{self.plan.replace(':', '')}-r{self.rate}-d{self.duration}"


SCENARIOS: dict[str, list[Scenario]] = {
    "latency": [Scenario("latency", 200, 300)],
    "knee": [Scenario("knee", r, 120) for r in (500, 1000, 2000, 4000)],
    "late": [Scenario("late", 200, 120, f"late:{s}") for s in (0, 30, 120)],
    "dup": [Scenario("dup", 200, 120, "dup")],
    "recovery": [Scenario("recovery", 200, 300, kill_at=120.0)],
    # Harness check only (one short run per engine); not part of the reported results.
    "smoke": [Scenario("smoke", 200, 60)],
}


class Engine:
    """A running engine job (its `docker compose exec` client) and its stdout."""

    def __init__(self, cmd: list[str], cwd: Path):
        self.proc = subprocess.Popen(
            cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace",
        )  # fmt: skip
        self.lines: list[str] = []
        self.errors: list[str] = []
        self.ready = threading.Event()
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._drain_err, daemon=True).start()

    def _read(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self.lines.append(line.rstrip())
            if line.startswith("progress ready"):
                self.ready.set()

    def _drain_err(self) -> None:
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            self.errors.append(line.rstrip())
            del self.errors[:-200]

    def result(self, timeout: float) -> dict[str, Any]:
        try:
            code = self.proc.wait(timeout)
        except subprocess.TimeoutExpired as exc:
            self.proc.kill()
            raise BenchError(f"engine did not drain within {timeout:.0f} s") from exc
        records = [line for line in self.lines if line.startswith("{")]
        if code or not records:
            tail = "\n".join(self.errors[-30:] + self.lines[-20:])
            raise BenchError(f"engine exited with {code}:\n{tail}")
        out: dict[str, Any] = json.loads(records[-1])
        return out


class MemorySampler:
    """Peak `docker stats` memory per container, sampled every 2 s."""

    def __init__(self, names: list[str]):
        self.names = names
        self.peak: dict[str, float] = dict.fromkeys(names, 0.0)
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    @staticmethod
    def _gib(text: str) -> float:
        units = {"KiB": 2**-20, "MiB": 2**-10, "GiB": 1.0, "TiB": 1024.0, "B": 2**-30}
        for unit, factor in units.items():
            if text.endswith(unit):
                return float(text[: -len(unit)]) * factor
        return 0.0

    def _run(self) -> None:
        while not self.stop.is_set():
            out = subprocess.run(
                ["docker", "stats", "--no-stream", "--format", "{{.Name}};{{.MemUsage}}",
                 *self.names],
                capture_output=True, text=True,
            ).stdout  # fmt: skip
            for line in out.splitlines():
                name, _, usage = line.partition(";")
                if name in self.peak:
                    used = self._gib(usage.split("/")[0].strip())
                    self.peak[name] = max(self.peak[name], used)
            self.stop.wait(2)

    def finish(self) -> dict[str, float]:
        self.stop.set()
        self.thread.join(10)
        return {k: round(v, 3) for k, v in self.peak.items()}


class AxisA:
    def __init__(self, host: Host, data_root: Path, log: Callable[[str], None]):
        self.host = host
        self.bench_dir = data_root / "exports" / "axis-a" / "bench"
        self.passages = data_root / "exports" / "axis-a" / "golden" / "passages.parquet"
        self.out = host.root / "results" / "benchmarks"
        self.policy = compare.Policy.load(host.root / "golden" / "axis-a-tolerance.json")
        self.contract = contract_commit(host.root)
        self.log = log

    # -- engines -------------------------------------------------------------------------------
    def _bring_up(self, engine: str) -> list[str]:
        wanted = SERVICES[engine]
        running = {n.removeprefix("transitometer-").removesuffix("-1") for n in self.host.running()}
        extra = sorted(s for s in running if s not in wanted)
        if extra:
            self.host.run("--profile", "*", "stop", *extra)
        self.host.run("--profile", "*", "up", "-d", "--wait", *wanted)
        if engine == "flink":
            folder = "/data/checkpoints/flink"
            prepare = f"mkdir -p {folder} && chown flink:flink {folder}"
            self.host.run("exec", "-T", "-u", "root", "flink-jobmanager", "sh", "-c", prepare)
            self._flink_wait(lambda jobs: True)  # REST up
        return self.host.require_only(*wanted)

    def _flink_jobs(self) -> list[dict[str, Any]]:
        with urllib.request.urlopen(f"{FLINK_REST}/jobs/overview", timeout=5) as resp:
            jobs: list[dict[str, Any]] = json.loads(resp.read())["jobs"]
            return jobs

    def _flink_wait(self, ok: Callable[[list[dict[str, Any]]], bool], timeout: float = 180) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if ok(self._flink_jobs()):
                    return
            except OSError:
                pass
            time.sleep(1)
        raise BenchError("Flink did not reach the expected state")

    @staticmethod
    def _flink_running(jobs: list[dict[str, Any]]) -> bool:
        """Every task is running, or already finished: a bounded source subtask that gets no
        Kafka partition (parallelism above the partition count) finishes right after start."""
        live = [j for j in jobs if j["state"] == "RUNNING"]
        return bool(live) and all(
            j["tasks"]["running"] > 0
            and j["tasks"]["running"] + j["tasks"]["finished"] == j["tasks"]["total"]
            for j in live
        )

    def _start(self, engine: str, run_dir: str, record: dict[str, Any], fresh: bool) -> Engine:
        if engine == "spark":
            cmd = self.host.compose(
                "exec", "-T", "spark", *SPARK_SUBMIT, f"{SRC}/pipeline/axis_a_spark.py",
                "--record", f"{run_dir}/record.json", "--trigger", "10 seconds",
                *(["--fresh"] if fresh else []),
            )  # fmt: skip
            job = Engine(cmd, self.host.root)
            if not job.ready.wait(240):
                raise BenchError("the Spark job did not report ready")
            return job
        offsets = {p: [b["start"], b["end"]] for p, b in record["partitions"].items()}
        cmd = self.host.compose(
            "exec", "-T", "flink-jobmanager", "flink", "run", "-py",
            f"{SRC}/axis_a/flink_job.py", "--offsets", json.dumps(offsets),
            "--topic", record["topic"],
        )  # fmt: skip
        job = Engine(cmd, self.host.root)
        self._flink_wait(self._flink_running)
        return job

    def _kill(self, engine: str) -> float:
        """SIGKILL the engine; returns the kill time (epoch ms)."""
        if engine == "spark":
            self.host.run(
                "exec", "-T", "spark", "pkill", "-9", "-f", "org.apache.spark.deploy.SparkSubmit"
            )
        else:
            subprocess.check_call(
                ["docker", "kill", "--signal", "KILL", container("flink-taskmanager")],
                stdout=subprocess.DEVNULL,
            )
        killed = time.time() * 1000
        if engine == "flink":
            subprocess.check_call(
                ["docker", "start", container("flink-taskmanager")], stdout=subprocess.DEVNULL
            )
        return killed

    # -- one run -------------------------------------------------------------------------------
    def run(self, engine: str, scenario: Scenario, number: int) -> dict[str, Any]:
        count = scenario.rate * scenario.duration
        slice_dir = self.bench_dir / f"slice-{scenario.plan.replace(':', '')}-{count}"
        record_file = slice_dir / "record.json"
        if record_file.exists():
            record = json.loads(record_file.read_text("utf-8"))
        else:
            record = axis_a_slice.prepare(self.passages, slice_dir, count, scenario.plan)
        container_dir = f"{EXPORTS}/{slice_dir.name}"
        run_id = f"{engine}-{scenario.label}-n{number}"
        run_dir = self.bench_dir / "runs" / run_id
        self.log(f"axis-a {run_id}: {count:,} passages at {scenario.rate}/s")
        started_at = now()
        containers = self._bring_up(engine)
        outputs = [f"kpi.{engine}.w1", f"kpi.{engine}.w2"]
        self.host.exec_json(
            "spark", "python3", "-m", "transitometer.bench.axis_a_kafka", "recreate",
            "--topics", record["topic"], *outputs,
        )  # fmt: skip
        sampler = MemorySampler([container(s) for s in SERVICES[engine] if s != "kafka"])
        job = self._start(engine, container_dir, record, fresh=True)
        produce_cmd = self.host.compose(
            "exec", "-T", "spark", "python3", "-m", "transitometer.bench.axis_a_kafka",
            "produce", "--run-dir", container_dir, "--rate", str(scenario.rate),
        )  # fmt: skip
        producer = Engine(produce_cmd, self.host.root)
        kill_ms = None
        if scenario.kill_at is not None:
            time.sleep(scenario.kill_at)
            kill_ms = self._kill(engine)
            if engine == "spark":
                job.proc.wait(60)
                job = self._start(engine, container_dir, record, fresh=False)
        produced = producer.result(scenario.duration * 4 + 300)
        if not produced["offsets_ok"]:
            raise BenchError(f"producer offsets differ from the record: {produced}")
        result = job.result(scenario.duration * 4 + 900)
        memory = sampler.finish()
        ends = json.dumps({p: b["end"] for p, b in record["partitions"].items()})
        dumps = {"input": (record["topic"], ends), "w1": (outputs[0], ""), "w2": (outputs[1], "")}
        for name, (topic, ends) in dumps.items():
            self.host.exec_json(
                "spark", "python3", "-m", "transitometer.bench.axis_a_kafka", "dump",
                "--topic", topic, "--out", f"{EXPORTS}/runs/{run_id}/{name}.parquet",
                *(["--ends", ends] if ends else []),
            )  # fmt: skip
        summary = self.analyze(run_dir, slice_dir, kill_ms)
        summary.update(
            {
                "engine": engine,
                "scenario": scenario.name,
                "plan": scenario.plan,
                "rate": scenario.rate,
                "duration_s": scenario.duration,
                "run": number,
                "passages": count,
                "faulted_passages": record["faulted_passages"],
                "rate_achieved": produced["rate_achieved"],
                "producer_max_behind_s": produced["max_behind_s"],
                "spark_dropped_by_watermark": sum(
                    result.get(w, {}).get("dropped_by_watermark", 0) for w in ("w1", "w2")
                )
                if engine == "spark"
                else None,
                "peak_memory_gib": round(sum(memory.values()), 3),
                "peak_memory_detail": json.dumps(memory),
                "started_at": started_at,
                "containers": " ".join(containers),
                "contract": self.contract,
                "send_sha256": record["send_sha256"],
            }
        )
        return summary

    # -- analysis ------------------------------------------------------------------------------
    def analyze(self, run_dir: Path, slice_dir: Path, kill_ms: float | None) -> dict[str, Any]:
        rel = {
            n: f"read_parquet('{(run_dir / f'{n}.parquet').as_posix()}')"
            for n in ("input", "w1", "w2")
        }
        out: dict[str, Any] = {}
        with duckdb.connect() as con:
            con.execute(f"CREATE VIEW inp AS SELECT * FROM {rel['input']} WHERE grp <> '__end__'")
            bounds = con.execute("SELECT min(append_ms), max(append_ms) FROM inp").fetchone()
            first, last = bounds if bounds else (0, 0)
            warmup = int(first) + WARMUP_MS
            for name in ("w1", "w2"):
                con.execute(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM {rel[name]}")
                measure = lat.w1_latencies if name == "w1" else lat.w2_latencies
                latencies = measure("inp", name, warmup)
                dist = lat.distribution(con, latencies)
                out[f"{name}_samples"] = dist["samples"]
                for p in ("p50_ms", "p95_ms", "p99_ms", "max_ms"):
                    out[f"{name}_{p}"] = dist[p]
                out[f"{name}_percentiles"] = dist["percentiles_ms"]
                keys = ", ".join(OUTPUT_KEYS[name])
                dupes, total, last_out = con.execute(
                    f"SELECT count(*) - count(DISTINCT ({keys})), count(*), max(append_ms) "
                    f"FROM {name}"
                ).fetchone() or (0, 0, 0)
                out[f"{name}_output_duplicates"] = int(dupes)
                out[f"{name}_last_output_lag_ms"] = int(last_out) - int(last) if total else None
                deduped = run_dir / f"{name}-dedup.parquet"
                golden_file = (slice_dir / "golden" / f"{name}.parquet").as_posix()
                golden_cols = [
                    row[0]
                    for row in con.execute(
                        f"DESCRIBE SELECT * FROM read_parquet('{golden_file}')"
                    ).fetchall()
                ]
                con.execute(
                    f"COPY (SELECT {', '.join(golden_cols)} FROM {name} "
                    f"QUALIFY row_number() OVER (PARTITION BY {keys} ORDER BY append_ms) = 1) "
                    f"TO '{deduped.as_posix()}' (FORMAT parquet)"
                )
                diff = self._compare(name, slice_dir, deduped)
                out[f"{name}_missing"] = diff.missing_rows
                out[f"{name}_extra"] = diff.extra_rows
                out[f"{name}_mismatched"] = sum(diff.mismatches.values())
                out[f"{name}_equal_golden"] = diff.ok
            if kill_ms is not None:
                resumed = con.execute(
                    f"SELECT min(append_ms) FROM (SELECT append_ms FROM w1 UNION ALL "
                    f"SELECT append_ms FROM w2) WHERE append_ms > {kill_ms}"
                ).fetchone()
                out["resume_ms"] = int(resumed[0] - kill_ms) if resumed and resumed[0] else None
            else:
                out["resume_ms"] = None
        sustained = (
            out["w2_p95_ms"] is not None
            and out["w2_p95_ms"] <= SLO_P95_MS
            and out["w2_last_output_lag_ms"] is not None
            and out["w2_last_output_lag_ms"] <= SLO_DRAIN_MS
        )
        out["sustained"] = sustained
        return out

    def _compare(self, name: str, slice_dir: Path, deduped: Path) -> compare.TableDiff:
        import pyarrow.parquet as pq

        expected = pq.read_table(slice_dir / "golden" / f"{name}.parquet")
        actual = pq.read_table(deduped)
        columns = {c: self.policy.tolerance(name, c) for c in expected.column_names}
        return compare.compare(name, expected, actual, self.policy.keys(name), columns)

    # -- scenarios -----------------------------------------------------------------------------
    def scenario(self, name: str, runs: int = 3) -> None:
        summaries: list[dict[str, Any]] = []
        points: list[dict[str, Any]] = []
        for scenario in SCENARIOS[name]:
            for number in range(1, runs + 1):
                order = ("spark", "flink") if number % 2 else ("flink", "spark")
                for position, engine in enumerate(order, start=1):
                    summary = self.run(engine, scenario, number)
                    summary["position"] = position
                    for workload in ("w1", "w2"):
                        for pct, value in enumerate(summary.pop(f"{workload}_percentiles")):
                            points.append(
                                {
                                    "engine": engine,
                                    "scenario": scenario.name,
                                    "plan": scenario.plan,
                                    "rate": scenario.rate,
                                    "run": number,
                                    "workload": workload,
                                    "percentile": pct,
                                    "latency_ms": round(value, 1),
                                }
                            )
                    summaries.append(summary)
                    write_csv(self.out / f"axis_a_{name}_runs.csv", summaries)
                    write_csv(self.out / f"axis_a_{name}_percentiles.csv", points)
        self.host.run("--profile", "*", "stop")
