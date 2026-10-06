# Transitometer

[![ci](https://github.com/Lorcelmao/transitometer/actions/workflows/ci.yml/badge.svg)](https://github.com/Lorcelmao/transitometer/actions/workflows/ci.yml)
[![Live site](https://img.shields.io/badge/live%20site-transitometer.vercel.app-0b5394)](https://transitometer.vercel.app/)
[![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

**Was the promised transit service actually delivered?** Transitometer is a streaming and lakehouse data pipeline that measures bus and subway reliability from real GTFS-Realtime feeds. It covers on-time performance, headway regularity and bunching, and feed data quality. Every Spark output table is compared with a separately built DuckDB reference. Started as a CO5173 Data Engineering course project (HCMUT).

**Live:** [public site](https://transitometer.vercel.app/) (static snapshot of a validated run) · [why and how it was built](https://transitometer.vercel.app/about/) · [evidence behind the numbers](https://transitometer.vercel.app/data/validation/) · [analyst console](https://transitometer.streamlit.app/) (Streamlit; may take up to a minute to wake)

- Real data: archived New York MTA feeds (bus trip updates, bus vehicle positions, subway 1–7/S trip updates) from [gtfsrt.io](https://gtfsrt.io), plus the matching static timetables.
- Pipeline: protobuf replay into **Kafka** → **Spark Structured Streaming** (PySpark) → **Delta Lake** Silver and Gold → **DuckDB** → **Streamlit** app.
- Correctness: an independent **DuckDB SQL** batch pipeline over the raw archive is the golden reference. Spark output must match it within a written tolerance policy ([`golden/tolerance.json`](golden/tolerance.json)).

## Architecture

```mermaid
flowchart LR
    A[gtfsrt.io archive<br/>Parquet, 3 feeds] -->|fetch + SHA-256 manifest| L[(Landing zone)]
    S[MTA static GTFS<br/>timetables] --> L
    L -->|replay: protobuf per entity,<br/>paced, keyed, lineage| K[[Kafka topics]]
    K -->|Spark Structured Streaming<br/>decode · dedup · dead-letter| SV[(Delta Silver<br/>rows, snapshots)]
    SV -->|Spark batch<br/>stop-event inference + timetable match| SE[(Delta Silver<br/>stop events)]
    SE -->|Spark batch| G[(Delta Gold<br/>KPI tables)]
    G -->|DuckDB delta_scan| APP[Streamlit app]
    L -->|DuckDB SQL<br/>independent rules| GR[(Golden reference)]
    GR -.->|compare under tolerance policy| G
```

| Layer | Technology | What happens |
|---|---|---|
| Ingest | Python, gtfs-realtime-bindings, Kafka | Archived snapshots are re-encoded to GTFS-RT protobuf, one message per trip or vehicle, keyed by trip/vehicle id. The replay is paced by feed time (×speed) with an idempotent producer and records per-snapshot offset lineage. |
| Silver | Spark Structured Streaming, Delta | `from_protobuf` decoding; exact-duplicate removal within a 10 min event-time watermark; a dead-letter table for undecodable or incomplete messages; a conservation check (in = kept + duplicates + late + dead-lettered); exactly-once Delta sink (re-runs append nothing). |
| Silver events | Spark (batch) | Stop arrivals inferred from successive predictions, matched to the timetable in three tiers, with service-day handling for trips past midnight. |
| Gold | Spark (batch), Delta | BR1 on-time performance (−1/+5 min band) per route and hour, including bus terminal arrivals measured from GPS; BR2 observed headways classified as regular, bunched or gap; BR3 every scheduled trip classified as delivered, partial, missing, not run or unknown; BR4 segment travel times and exact delay attribution; BR5 route scorecards with bootstrap confidence and rank intervals; BR6 rule-based early warning against a naive baseline on a held-out day; BR7 twelve feed-quality checks with a conformance score; BR8 stop-level reliability by hour with Wilson intervals. |
| Serve | DuckDB, Streamlit, Next.js | One Python serving layer (`serve/kpis.py` queries, `serve/views.py` page rules and labels) feeds two frontends: the Streamlit app (Gold Delta, golden tables or the validated snapshot) and a static Next.js site built from the same views exported as JSON. |

## Quickstart

Requirements: Python 3.10+, Docker Desktop (Compose v2), about 35 GB free disk for Docker.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[dev]"
cp config/.env.example config/.env      # set TRANSITOMETER_DATA_ROOT to a folder outside the repo

python tasks.py fetch                   # pinned real data into <data root>/landing (verified)
python tasks.py build                   # Spark tooling image
python tasks.py demo                    # one real hour end to end, then the app
```

`demo` replays one real hour of all three feeds through Kafka, Spark Silver, stop-event inference and Gold, then starts the app at <http://localhost:8501>. Each step prints its progress. `python tasks.py down` stops everything; data volumes are kept.

To browse the app without running the pipeline, start it on the frozen golden tables: `TRANSITOMETER_APP_SOURCE=golden python tasks.py up app`. Or run it on the host, without Docker, on the committed validated snapshot of the Spark Gold tables (`showcase/data/`, see below): `pip install -e ".[app]"`, then `TRANSITOMETER_APP_SOURCE=snapshot streamlit run src/transitometer/app/main.py`.

## Full golden-window run and validation

```bash
python tasks.py replay            # golden window (2 service days, 3 feeds) into Kafka
python tasks.py replay-verify     # counts, markers, ordering, sampled field fidelity
python tasks.py silver            # Kafka -> Silver Delta
python tasks.py silver-events     # stop events, compared with golden -> results/validation-silver.json
python tasks.py gold              # Gold KPIs, compared with golden -> results/validation-gold.json
python tasks.py golden            # (re)build the golden reference with DuckDB
```

## Results

Every number below is read from a committed result file (named in each row). The golden window is the service days 22–23 September 2026, read from the UTC archive days 22–24.

**Source integrity: the stream is the archive, complete and unaltered**

| Check | Result | Evidence |
|---|---|---|
| Messages replayed into Kafka (3 feeds, incl. one marker per snapshot) | 52,756,838, all broker-acknowledged | `results/replay-report.json` |
| Archive rows they carry | 607,076,700 (bus trip updates 528,801,318 · subway 60,186,868 · bus positions 18,088,514) | `results/replay-report.json` |
| Read back from Kafka = acknowledged = archive entity count | equal for every feed; 0 timestamps backwards; 0 lineage overlaps | `results/replay-verification.json` |
| Sampled snapshots decoded field for field vs the archive | 60 of 60 equal (20 per feed) | `results/replay-verification.json` |
| Silver rows = archive rows | equal for every feed; 0 duplicates, 0 late, 0 dead-lettered; conservation balanced | `results/silver-ingest.json` |

**Golden-reference parity: Spark equals an independent DuckDB implementation**

| Layer | Tables equal / compared | Largest table | Evidence |
|---|---|---|---|
| Silver (stop events, matching, statuses) | 4 / 4 | `stop_events`: 2,955,606 rows | `results/validation-silver.json` |
| Gold (BR1–BR8, bus terminal arrivals) | 23 / 23 | `stop_hour_reliability`: 392,788 rows; `headways`: 2,956,930 rows | `results/validation-gold.json` |

Rows are matched on their keys; every other column must be equal, floats within the declared tolerance ([`golden/tolerance.json`](golden/tolerance.json)). Re-running the golden pipeline reproduces every frozen golden file byte for byte (checksums in `golden/checksums.json`).

**Alternative processing engine (Axis A): Spark and Flink on one passage stream**

Both engines read the same Kafka topic of 3,020,240 inferred passages (between recorded offsets; per-partition SHA-256 in `results/axis-a-produce.json`) and compute W1, 1-minute event-time windows of arrival delay per route and stop, and W2, the BR2 headway of each passage with keyed state. Golden W2 computed from the passages equals the golden `headways` table, so the stream is complete.

| Engine | W1 windows equal golden | W2 headways equal golden | Evidence |
|---|---|---|---|
| Spark 4.1 Structured Streaming | 2,919,421 / 2,919,421 | 2,956,930 / 2,956,930 | `results/validation-axis-a.json` |
| Flink 2.2 (PyFlink: SQL for W1, KeyedProcessFunction for W2) | 2,919,421 / 2,919,421 | 2,956,930 / 2,956,930 | `results/validation-axis-a.json` |

Both engines share one W2 state step (`axis_a/headway_state.py`), property-tested against the golden SQL. The engines do not re-infer stop events: they start from the inferred passages. Latency, throughput, lateness and recovery are measured in S10; the drained run times in `results/axis-a-*.json` are not a benchmark.

**Performance (one laptop, wall time; Spark `local[8]`, DuckDB 8 threads)**

| Step | Time | Evidence |
|---|---|---|
| Replay of the golden window into Kafka (3 feeds in parallel, unpaced) | 1,247 s (longest feed) | `results/replay-report.json` |
| Spark: stop events, timetable matching, statuses (Silver) | 481.8 s | `results/silver-events.json` |
| Spark: Gold KPI tables (BR1–BR8, terminals, stop names and locations) | 309.9 s | `results/gold-kpis.json` |
| DuckDB golden, the same rules (all steps but the 06 cross-check; sum of step times) | 711.0 s | `results/golden-run.json` |
| DuckDB golden, all 12 steps (BR1–BR8) | 892.1 s | `results/golden-run.json` |

This is the current alternative-solution comparison: a single-node batch engine (DuckDB, over the raw archive Parquet) against a distributed streaming/batch engine (Spark in Docker, over Silver Delta tables already decoded from Kafka). They are not like-for-like: DuckDB's time includes reading the raw archive, while Spark's times include JVM start-up and Delta writes but not the Kafka → Silver ingest that precedes them. The full benchmark suite (Flink, ClickHouse, scaling) is on the roadmap.

## Tasks

All commands go through `python tasks.py <task>` (works on every OS):

| Task | What it does |
|---|---|
| `check [--record]` | lint + typecheck + tests; `--record` writes the counts to `results/test-summary.json` (evidence shown in the app) |
| `fetch`, `validate-landing` | download and validate the pinned sources (manifest with SHA-256) |
| `build`, `up <profile>`, `down` | build the image, start services, stop everything (volumes kept) |
| `replay`, `replay-verify` | replay archived feeds into Kafka; verify the stream against the archive |
| `silver`, `silver-events`, `gold` | Spark jobs; `silver-events` and `gold` also export their tables and compare them with golden (`gold --export-only` re-exports and compares without re-running Spark) |
| `snapshot` | copy the validated Gold tables the app reads into `showcase/data/`, with the run's evidence files and a manifest (commit, rows, SHA-256); refuses unless validation passed and the exports match the validated run |
| `web-data [--check]` | export the shared views over the snapshot as JSON for the Next.js site (`web/public/data/`) and the cross-frontend parity file; `--check` fails if the committed JSON is stale |
| `demo [--fresh]` | one real hour end to end, then the app |
| `golden`, `golden-check` | build the DuckDB golden reference; check result tables against it |
| `storage-check`, `storage-report` | storage guard (warn at 30 GB, refuse engine starts at 35 GB) and usage log |

Runs on any topic prefix other than `rt` (for example the demo) write to their own lakehouse subtree and report folder (`results/scratch/<prefix>/`), so they never touch the validated tables.

## Two frontends

| Frontend | For | Runs where | Data |
|---|---|---|---|
| Next.js site (`web/`) | the public showcase: editorial pages, interactive charts, evidence | static files (Vercel Hobby) | JSON exported from the views over the validated snapshot (`python tasks.py web-data`) |
| Streamlit app (`src/transitometer/app/`) | the analyst console | local, Docker `app` profile, or Streamlit Community Cloud | the same views, live over Gold Delta, the golden tables or the snapshot |

Every metric, threshold, ranking, pass rule and definition is computed once, in `src/transitometer/serve/views.py`; neither frontend defines one of its own. Both are tested against one file of expected headline values (`showcase/contract/parity-expected.json`): Streamlit with headless app tests, the site with Playwright. See [`web/README.md`](web/README.md) for the site.

## Hosted app (validated snapshot)

The public app runs the same Streamlit code on `showcase/data/`, a committed copy of the validated Spark Gold tables (`python tasks.py snapshot`). It needs no Docker, Kafka, Spark or lakehouse: every page names the commit and date of the validated run, and its evidence comes from the copies in `showcase/data/evidence/`.

- Streamlit Community Cloud: entrypoint `src/transitometer/app/main.py`, Python 3.12, secret `TRANSITOMETER_APP_SOURCE = "snapshot"`. It installs `src/transitometer/app/requirements.txt` (pinned like the Spark image) and imports the package from the clone.
- The CI `hosted-app` job reproduces that environment (hosted requirements only, no package install, no data) and renders every page.

## Repository map

- `src/transitometer/replay/`: archive → protobuf → Kafka, verification
- `src/transitometer/pipeline/`: Spark jobs (`silver_ingest`, `silver_events`, `gold_kpis`) and export
- `src/transitometer/golden/`: DuckDB golden SQL, tolerance comparison, 25-query suite
- `src/transitometer/serve/`: data-access layer (`kpis.py`), shared page views and formatting (`views.py`, `format.py`), snapshot and web export
- `src/transitometer/app/`: Streamlit app; `web/`: Next.js site; `showcase/`: validated snapshot and the cross-frontend contract files
- `PROJECT_PLAN.md`: scope, users and business requirements; `IMPLEMENTATION_PLAN.md`: stages and tests

## Roadmap

All eight core requirements run in Spark and match the golden reference: BR1 on-time performance, BR2 headways and bunching, BR3 missing trips, BR4 delay attribution, BR5 route scorecards, BR6 early warning, BR7 feed health and BR8 stop reliability. The public showcase is deployed (Next.js on Vercel, Streamlit on Community Cloud). Next: the benchmarked alternatives (Flink for processing, ClickHouse for serving) and the Ho Chi Minh City static network case study. See `IMPLEMENTATION_PLAN.md`.

## Storage rules

Data never goes into Git. Raw/landing data, golden results and exports live in the host data root (`TRANSITOMETER_DATA_ROOT`); Docker holds only rebuildable working state and should stay at or below 25 GB.

## Data and licence

Source data: archived MTA GTFS-Realtime feeds (via the [gtfsrt.io](https://gtfsrt.io) archive) and MTA static timetables, used under the [MTA Terms of Use](https://www.mta.info/developers/terms-and-conditions). Transitometer is not an official MTA product and is not endorsed by the MTA. The repository publishes only derived tables (the validated snapshot and the golden reference), never raw feed data.

Code: [MIT](LICENSE).

## Contributing

`main` must always pass `python tasks.py check`; CI runs the same checks plus the web build, end-to-end and Lighthouse tests.
