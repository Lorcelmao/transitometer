# Reproducibility

Everything a run depends on is pinned in a file that the code checks. This page says which file pins what, records the machine the published results came from, and records the clean-clone test.

## What is pinned, and where

| Input | Pinned in | Checked by |
|---|---|---|
| Source data (MTA archive, GTFS) | [`data-manifest.json`](../data-manifest.json): every file with its SHA-256 | `python tasks.py fetch` and `validate-landing` |
| Docker images (Kafka, Spark base, Flink base, ClickHouse) | [`docker/versions.env`](../docker/versions.env): tag and digest | `python tasks.py verify-lock` |
| Python packages in the Spark tooling image | [`docker/spark-tools/requirements.lock`](../docker/spark-tools/requirements.lock) | image build |
| JVM libraries (Delta, Kafka, Protobuf connectors) | `docker/versions.env` (`DELTA_VERSION`, `SPARK_*_ARTIFACT`, `FLINK_KAFKA_CONNECTOR_VERSION`) | image build |
| Host Python packages (tooling, app) | [`pyproject.toml`](../pyproject.toml) (`dev`, `app` extras) | `pip install -e ".[dev]"` |
| Web site | [`web/package.json`](../web/package.json) and its lock file | `npm ci` |
| Golden reference (DuckDB) | `golden/checksums.json`: SHA-256 of every frozen table and query answer | `python tasks.py golden-check` |
| Validated snapshot the hosted app reads | [`showcase/data/manifest.json`](../showcase/data/manifest.json): commit, rows, SHA-256 | `python tasks.py snapshot` refuses a mismatch |
| Benchmark method | [`docs/benchmark-fairness.md`](benchmark-fairness.md), committed before the first run (1d35e18); every raw CSV row records that commit | `python tasks.py bench-report` |

## Reference machine (measured 2026-10-29)

| | |
|---|---|
| Laptop | ASUS TUF F15, Intel Core i7-12700H (14 cores, 20 threads), 31.6 GB RAM |
| OS | Windows 11 Home 10.0.26200 |
| Docker | Docker Desktop 4.54.0, Engine 29.1.2, Compose 2.40.3, WSL2 backend |
| WSL | 2.3.26.0, kernel 5.15.167.4; `.wslconfig`: `memory=18GB`, swap file on D: |
| Docker VM | 20 CPUs, 17.6 GiB |
| Docker data | `D:\DockerDesktop\DockerDesktopWSL` (`TRANSITOMETER_DOCKER_VHDX` in `config/.env.example`) |
| Host tools | Python 3.10.6 (minimum supported; CI also runs it), Node 22 |

Resource caps that shape the results: Spark `local[8]` with a 6 GB driver, Flink parallelism 8, DuckDB and ClickHouse 8 threads (fairness contract); the storage guard warns at 30 GB of Docker usage and refuses engine starts at 50 GB (`config/.env.example`).

## Clean-clone test

The README quickstart, run step by step on a fresh clone of `main`, with the existing data root reused (so `fetch` verifies every file's checksum instead of downloading 12 GB again):

```bash
git clone https://github.com/Lorcelmao/transitometer.git
python -m venv .venv && .venv\Scripts\python -m pip install -e ".[dev]"
copy config\.env.example config\.env
python tasks.py fetch
python tasks.py build
python tasks.py demo
```

Result on 2026-10-29 (Python 3.10.6), 748 s in all, every step exit code 0:

| Step | Time | Outcome |
|---|---|---|
| clone, virtual environment, `pip install -e ".[dev]"` | 49 s | |
| `fetch` | 5.8 s | 94 files (12.31 GB): every SHA-256 equal to the manifest, nothing downloaded |
| `build` | 339 s | Spark tooling image built from the pinned base and lock file |
| `demo` | 352 s | one real hour replayed (7,055,119 bus trip-update rows, 913,200 subway, 246,054 bus positions), Silver balanced, 65,867 stop events, all Gold tables exported |
| app | 2 s | `http://localhost:8501` answers 200 |

**Determinism.** The demo's reports were compared with those of the run of 2026-10-02 on every count both report (replay rows, Silver messages and rows, stop events, Gold table rows): 65 of 65 equal. Timings, paths and timestamps are left out because they differ by nature. The golden reference itself was rerun in full during S5 and reproduced every frozen file byte for byte (`golden/checksums.json`).
