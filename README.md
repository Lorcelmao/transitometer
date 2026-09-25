# Transitometer

A streaming + lakehouse data-engineering platform that measures urban transit reliability:
*was the promised service actually delivered?* CO5173 Data Engineering course project (HCMUT).

Real archived GTFS-Realtime data (gtfsrt.io) is replayed as protobuf through **Kafka**, processed by
**Spark Structured Streaming** into a **Delta Lake** lakehouse, checked against an independent
**DuckDB** golden reference, and served to a **Streamlit** app. **Flink** (processing) and
**ClickHouse** (serving) are the benchmarked alternatives.

- Scope, architecture, requirements: [`PROJECT_PLAN.md`](PROJECT_PLAN.md)
- Stages, tests, storage budget: [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md)

## Setup (host)

Requires Python 3.10+ and Docker Desktop (Compose v2).

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[dev]"
cp config/.env.example config/.env   # then adjust paths for your machine
```

In `config/.env`, point `TRANSITOMETER_DATA_ROOT` at a folder outside the repo, e.g.
`D:/Transitometer-data` on Windows or `/home/<you>/transitometer-data` on Linux/macOS, and set
`TRANSITOMETER_DOCKER_VHDX` to your Docker Desktop disk image path (leave it empty if unknown).

## Tasks

All project commands go through `python tasks.py <task>` (works on every OS):

| Task | What it does |
|---|---|
| `check` | lint + typecheck + tests |
| `fetch [--only realtime\|schedule] [--workers N] [--accept-changes]` | download the pinned sources in `config/sources.json` into `<data root>/landing`, verified against `data-manifest.json` |
| `validate-landing` | validate the landing zone and write `results/landing-volume-report.json` |
| `compose-config` | validate `docker/compose.yaml` for every profile |
| `verify-lock` | confirm pinned image digests in `docker/versions.env` still match the registry |
| `storage-check` | soft storage guard: warn at 25 GB, refuse engine starts at 30 GB |
| `storage-report` | print Docker usage and append it to `<data root>/results/storage-log.csv` |
| `up <kafka\|spark\|app\|flink\|clickhouse>` | storage guard, then start Kafka or a profile |
| `down` | stop all services (named volumes are kept) |

## Storage rules

Data never goes into Git. Raw/landing data, golden results and benchmark outputs live in the host
data root (`TRANSITOMETER_DATA_ROOT`, default `D:/Transitometer-data`); Docker holds only
rebuildable working state and should stay at or below 25 GB. See `PROJECT_PLAN.md` §1.3.

## Collaboration

Feature branch → pull request → review by at least one other member → merge to `main`.
`main` must always pass `python tasks.py check`.
