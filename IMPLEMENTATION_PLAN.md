# IMPLEMENTATION PLAN — Transitometer

**Dependency-ordered stages with testing/validation at every stage, explicit run locations, and a storage budget.**

| | |
|---|---|
| **Companion to** | `PROJECT_PLAN.md` v2 (scope, architecture, BRs, evaluation) |
| **Course / domain** | CO5173 Data Engineering · Transportation |
| **Team** | 4 students — logical ownership only; **one runtime machine** |
| **Host** | ASUS TUF F15 · i7-12700H (14C/20T) · 31.6 GB RAM · Win 11 Home · Docker Desktop 4.54.0 (engine 29.1.2, Compose v2.40.3) |
| **Status** | Plan **v2.1** — host prerequisites done; no implementation started; S0 starts on owner go-ahead |
| **Date** | v1 2026-09-23 · v2 2026-09-25 · **v2.1 2026-09-25** (renamed Transitometer; soft storage guard) |
| **Repository** | `github.com/Lorcelmao/transitometer` (created in S0) |

> **Binding constraints from `PROJECT_PLAN.md`:** real data for all BR results and acceptance (§1.1) · single machine,
> one engine profile at a time (§1.2) · two-zone storage, Docker ≤ 25 GB steady, soft guard at 25/30 GB (§1.3) ·
> core = BR1–BR8 + Axis A + Axis B (§16).

---

## 1. Plan principles

1. **Integrate early, then deepen.** A walking skeleton (S2, weeks 2–3) proves the whole chain on one real hour before any KPI logic depends on it.
2. **Independent oracle before engines.** KPI semantics are fixed first as **DuckDB SQL on landing Parquet** (golden), independent of Kafka, protobuf re-encoding and Spark; every engine is graded against it.
3. **One production engine.** Spark implements the full pipeline (streaming + batch). Flink implements **only** the Axis A benchmark workload (W1, W2). No logic is written three times.
4. **Containers for JVM engines.** Spark and Flink run only in Java 17 containers; the host runs Python tooling (fetch, DuckDB golden, tests) only.
5. **Docker holds only reproducible working state.** Records (landing data, golden, results, exports) live on `D:\Transitometer-data` or in Git; the engine zone can be cleaned at phase boundaries.
6. **Tests ship with the stage.** No stage is done without its tests and exit criterion.
7. **Fairness by construction.** Shared benchmark harness; identical Kafka offsets; latency from Kafka append times.

---

## 2. Stage map

| Stage | Goal | Depends on | Runs on | Primary test focus |
|---|---|---|---|---|
| **S0** | Host prerequisites, repo, tooling, pinned images, Compose | — | host + Docker | lint, `compose config`, image digest check, storage baseline |
| **S1** | Real-data acquisition → landing zone + manifest | S0 | host | checksums, provenance, GTFS validity, measured volumes |
| **S2** | **Walking skeleton** + storage calibration gate | S0, S1 (1 hour of data) | Docker | E2E smoke on real hour; measured footprint vs budget |
| **S3** | Replay harness + canonical schemas (protobuf re-encode) | S2 | host (unit) + Docker (integration) | round-trip fidelity, pacing, determinism, fault injection |
| **S4** | DuckDB golden KPIs ★ | S1 | host | hand-checked samples, invariants, service-day edge cases |
| **S5** | Golden freeze + correctness harness + 25-query suite | S4 | host | byte-reproducible golden; frozen suite |
| **S6** | Spark Silver (decode, dedup, stop events, schedule join, DQ) | S3, S5 | Docker (`spark`) | Silver vs golden intermediates; conservation; idempotence |
| **S7** | Spark Gold BR1–BR8 (streaming + batch) + Delta maintenance | S6 | Docker (`spark`) | Gold vs golden; late data; recovery; time travel |
| **S8** | Flink Axis A workload (W1, W2) | S3, S5 | Docker (`flink`) | parity vs golden and vs Spark on identical offsets |
| **S9** | ClickHouse + Axis B serving comparison | S7 | Docker (`clickhouse`) | 25-query parity across B1/B2/B3 |
| **S10** | Benchmarks (Axis A, Axis B, real-data scaling) + phase cleanup | S7, S8, S9 | Docker | repeatability, counterbalance, idle-host check |
| **S11** | Streamlit application (U1–U7) | S5 (dev on golden exports), S7 | host (dev) + Docker (`app`) | data-access unit tests, UI smoke, per-BR acceptance |
| **S12** | E2E, reproducibility, evaluation packaging | S10, S11 | Docker | clean-clone E2E, criteria coverage |
| **S13** | Desirable/optional: BR9, BR10, BR11, extras | S7 (BR9/10), S1 (BR11) | Docker / host | parity with core pipeline, validity |
| **S14** | Submission artifacts | S12 | host | artifact checklist, group-ID naming |

---

## 3. Where things run

| Component | Host (Windows, Python 3.10 venv on D:) | Container |
|---|---|---|
| `fetch_data.py`, manifest, checksums | ✅ | — |
| DuckDB golden SQL, correctness suite, property tests | ✅ | also runnable in the Spark/tooling image (CI parity) |
| Replay harness (re-encode, pacing, faults) | unit tests | ✅ runs against Kafka (reads landing via **read-only** mount) |
| Kafka (KRaft) | — | ✅ `apache/kafka` |
| Spark Structured Streaming + batch | — | ✅ custom image FROM official Apache Spark (Java 17, Python 3) |
| Flink / PyFlink | — | ✅ custom image FROM official `flink` Java 17 + Python + PyFlink |
| ClickHouse | — | ✅ `clickhouse/clickhouse-server` (Axis B phase only) |
| Streamlit app | ✅ dev against small exports | ✅ `app` profile (same image as Spark/tooling) reading Delta via DuckDB |
| Report, slides, video | ✅ | — |

The host needs **no JDK**. Host Java 23 is irrelevant to the stack.

---

## 4. Storage budget & operations (Docker ≤ 25 GB steady)

### 4.1 Zones
- **Host zone `D:\Transitometer-data\`**: `landing/` (file-based Bronze, immutable), `golden/`, `results/`, `exports/`. Expected ~20–30 GB [E]; may grow if the window grows.
- **Engine zone (Docker disk image at `D:\DockerDesktop\DockerDesktopWSL`)**: named volumes `kafka-data`, `lakehouse` (Delta Silver/Gold + `meta.ingest_log`), `checkpoints`, `clickhouse-data` (Axis B only), `scratch` (temporary staging); images; build cache.

### 4.2 Budget by component [E — recalibrated at S2]

| Component | Steady | Controls |
|---|---|---|
| Images: Kafka + Spark/tooling | **4.6–4.8 GB measured** (on-disk, containerd store) | One Python-bearing Spark image also runs the replay harness, DuckDB and Streamlit; connector jars + DuckDB extensions baked; containerd store overhead included |
| Image: Flink + PyFlink | 0 outside S8/S10-A; 1.6–2.0 GB during | Pull/build in phase; remove after Axis A results are exported; digest-pinned so rebuild is identical |
| Image: ClickHouse | 0 outside S9/S10-B; ~0.7 GB during | same |
| Build cache | ≤ 2 GB | `docker builder prune --keep-storage 2GB` after every image build |
| Kafka log | ≤ 3 GB (hard) | `compression.type=zstd`; per-topic `retention.ms=86400000` and `retention.bytes` sized so all topics ≤ 3 GB; `segment.bytes=128MB`; replays regenerate from landing, so nothing depends on retention |
| Delta Silver + Gold + lineage | 5–10 GB | No Bronze payload copy (Bronze = landing on D:); Silver stores deduped observations and inferred stop events, **not** every repeated snapshot row; partition by `service_date`; `OPTIMIZE` + `VACUUM` weekly |
| Streaming checkpoints / state | ≤ 1 GB | Deleted between benchmark runs and after stage exits |
| ClickHouse data | 0 outside Axis B; 2–5 GB during | Loaded from Delta; system log tables TTL-limited; `DROP` after results exported |
| Containers + logs | < 0.5 GB | Compose `logging: max-size 10m, max-file 3`; `docker compose down` between phases |

### 4.3 Budget by phase [E]

| Phase | Docker logical usage | Notes |
|---|---|---|
| S2–S7 normal development | **~18–21 GB** | Kafka + Spark images, Delta, Kafka log, cache |
| S8 + S10-A (Flink) | ~21–23 GB | + Flink image/state |
| S9 + S10-B (ClickHouse) | ~21–25 GB | Flink image removed first; + ClickHouse image/data |
| **Temporary peak** — real-data scaling runs (7-day slice staged into `scratch`) + `OPTIMIZE` rewrite | **~30–35 GB** | Only if S2 shows mount reads > 20% of Spark runtime; otherwise read slices from the read-only mount and skip staging. **S2 measured 8–15 % → staging not needed** (steady peak stays ≈ 15–20 GB) |

**Verdict:** ≤ 25 GB is **sustainable in normal development** with the controls above; it is **not** sustainable
through the scaling/compaction peak. **Compromise target:** ≤ 25 GB steady, peaks confined to scheduled windows and followed by cleanup + compaction.
Docker Desktop 4.54 (WSL2 mode) offers **no hard disk-usage limit**, so the ceiling is enforced by the **soft storage
guard** `python tasks.py storage-check` (reads `docker system df` + VHDX file size): **warn ≥ 25 GB**, **refuse to start new
engine runs ≥ 30 GB** (override only via an explicit flag during a scheduled peak phase). Every `tasks.py up <profile>`,
`tasks.py replay` and `tasks.py bench` task calls it first.

### 4.4 Docker disk image behaviour (measured)
`docker_data.vhdx` is **non-sparse**: the file keeps its high-water size after data is deleted. Therefore:
- **Phase-boundary compaction** after S10 peaks (and whenever the file exceeds ~30 GB while logical usage is ≤ 25 GB): stop Docker Desktop → `wsl --shutdown` → `diskpart` `select vdisk file=...` / `attach vdisk readonly` / `compact vdisk` / `detach vdisk` (admin). Owner runs or approves each time.
- **Last-resort reset:** because the engine zone is reproducible, *Troubleshoot → Clean / Purge data* + rebuilding images and re-running from landing is an acceptable recovery path (costs rebuild time, not data).

### 4.5 Operations checklist
- **Weekly:** `docker system df -v`, VHDX file size, `du` of named volumes → append to `results/storage-log.csv`.
- **After image builds:** `docker builder prune --keep-storage 2GB`; `docker image prune` (dangling only).
- **Before every benchmark run:** `docker ps` shows only the arm under test + Kafka; checkpoints cleared.
- **Phase exit (S8, S9, S10):** export results to `results/`, then remove that phase's image, volumes and checkpoints; record before/after in the storage log.
- **Never:** bind-mount `landing/` read-write; build images with data in context (build contexts are only the small `docker/spark-tools/` and `docker/flink-py/` folders).

---

## 5. Detailed stages

Each stage: **Goal → Deliverables → Tests → Exit.**

### S0 — Host prerequisites & foundations
- **Status (2026-09-25):** ✅ implemented and verified — `tasks.py check` green (31 tests), compose valid for all profiles, lock digests verified, storage baseline logged; independent code review + test pass findings resolved. Build-time items deferred to the stages that first build each image (S2 Spark image, S8 Flink image, S9 ClickHouse).
- **Goal:** a cloneable repo and a host whose Docker storage is on D: within budget.
- **Deliverables:**
  - **Host prerequisites — ✅ done 2026-09-25:** Docker disk image at `D:\DockerDesktop\DockerDesktopWSL`; `.wslconfig` `memory=18GB` + `swapFile=D:\WSL\swap.vhdx`; `D:\Transitometer-data\{landing,golden,results,exports}`. Hard disk limit unavailable → soft storage guard below.
  - Git repo `Lorcelmao/transitometer` + branch/PR policy; `pyproject.toml` (ruff, mypy, pytest); `src/` layout; `tasks.py` stdlib task runner (`check compose-config verify-lock storage-check storage-report up <profile> down`, later `fetch golden replay bench clean-phase`); `.gitignore`; `config/` (env-driven, no secrets).
  - `docker/compose.yaml`: `kafka` (no profile), profiles `spark`, `flink`, `clickhouse`, `app`; named volumes; logging limits.
  - Pinned versions: Spark 4.x + matching Delta 4.x pair; Flink 2.x + `flink-connector-kafka` 4.x; image digests.
  - Two custom Dockerfiles: `spark-tools` (Spark + Delta + Kafka connector jars, `gtfs-realtime-bindings`, `protobuf`, `pyarrow`, `duckdb` + `delta`/`spatial` extensions pre-installed, `streamlit`); `flink-py` (Flink + Python + PyFlink + Kafka connector). Flink image is **authored** here but built in S8.
- **Tests:** `python tasks.py check` green; `docker compose config -q`; image digests match lock file; storage baseline recorded (VHDX path on D:, size, `docker system df`).
- **Exit:** fresh clone → `python tasks.py check` green; Docker disk verified on D:.

### S1 — Real-data acquisition & landing zone — host
- **Status (2026-09-25):** ✅ implemented and verified. Owner-approved scope changes: **7 service days 2026-09-17 → 09-23** (not 14); BR9 history, Hanoi/OSM and Open-Meteo **deferred to S13** (same fetch code, new `config/sources.json` entries); manifest is **JSON** (`data-manifest.json`, stdlib) instead of YAML; GTFS validity is checked with DuckDB/pyarrow (the archive serves schedules as Parquet tables, so `gtfs_kit` does not apply).
- **Measured results** (`results/landing-volume-report.json`):
  - **1.48 × 10⁹ real-time rows, 12.3 GB** (94 files incl. schedules). Weekday ≈ 1.66 GB/day, weekend ≈ 1.1 GB/day.
  - Archive `date=` partitions are **UTC days**; the window is NYC service days, so the fetch includes the following UTC day (window.end + 1).
  - All 7 schedule versions (6 MTA Bus boroughs/companies + subway, pinned by content digest from the gtfsrt.io archive) cover every window day, cross-checked against `feed_info`.
  - Snapshot gaps ≤ ~1 min in all feeds.
  - Real archive gap found outside the window: MTA Bus trip updates missing on 2026-09-05 (BR7 evidence).
  - **Trip-id matching:** MTA Bus 99.2% exact. NYCT subway 84.1% across tiers (suffix after first `_`; origin time + route + direction). Remaining ~16% = added/unscheduled or retimed trips; ~61% of those lie within ±2 min of a scheduled trip on the same route and direction. **S4 must define the matching policy** (tiers + time tolerance + an explicit "unscheduled" label).
- **Goal:** real data pinned and measured.
- **Deliverables:** `data-manifest.yaml` (URL, retrieval timestamp, licence, SHA-256, rows, bytes); `fetch_data.py`:
  - gtfsrt.io Parquet: **MTA Bus** trip updates + vehicle positions and **one subway feed group** (default `nyct/gtfs`) for the **core window** (7 service days, see status above);
  - GTFS static: subway versions from gtfsrt.io `schedules/` covering the window; MTA Bus static from MTA (+ Mobility Database historical versions if needed);
  - BR9 history: **corridor subset** (default: the subway group, Jan 2026 →, filtered at download with pyarrow predicates) — size capped;
  - Hanoi GTFS + OSM extract (BR11), Open-Meteo (BR10) — small.
  - **Golden window:** 48 h sub-window of the core window (no separate download).
- **Decision gates:** (1) static-schedule versions exist for every core-window date (else move the window into one static version); (2) measured size of window + history within ~30 GB host-zone target (else shrink window/corridor).
- **Tests:** checksum verification; schema presence per file; GTFS validity (`gtfs_kit`); licence per source; rows/bytes per day recorded.
- **Exit:** `python tasks.py fetch` reproduces the landing zone from the manifest; volume report committed.

### S2 — Walking skeleton & storage calibration — Docker
- **Status (2026-09-26):** ✅ implemented and verified (`results/storage-calibration.json`).
  - One real hour (2026-09-22 14:00–15:00 UTC, MTA Bus vehicle positions): 298,860 archive rows → 298,860 **broker-acknowledged** protobuf messages (one per entity, 120 snapshots) → 298,860 Silver Delta rows via Spark Structured Streaming with native `from_protobuf` → DuckDB 298,860 rows / 3,280 vehicles → Streamlit renders. Re-run on the same checkpoint appends 0 rows. Re-encode round trip on the real hour: 0 mismatched fields.
  - **Storage calibration:** images 4.6–4.8 GB on disk (containerd keeps compressed + unpacked layers; build cache is shared with image layers, so the storage guard counts only its unshared part); Kafka ≈ 15 MB and Silver ≈ 6.5 MB per replayed hour; **projected steady usage ≈ 15 GB ≤ 25 GB**. The Docker disk file sits at ≈ 13 GB after image builds (non-sparse high-water mark).
  - **Mount read overhead 8–15 %** (lower bound; page cache not controlled) → scale runs read landing directly; the 30–35 GB staging peak is **not needed** (re-measure cold in S10).
  - Hardening from review: connector jars are de-duplicated against Spark's own jars and the build fails on a clash (`docker/spark-tools/install-jars.sh`); Python packages pinned by `docker/spark-tools/requirements.lock`; failed runs overwrite the report with `ok: false`; Kafka health check runs every 60 s with a 64 MB heap.
  - Semantics decision: when a feed omits `current_status`, Silver keeps the GTFS-RT spec default (IN_TRANSIT_TO); S4 golden SQL applies the same rule.
- **Goal:** prove the whole chain on **one real hour** and calibrate the storage budget.
- **Deliverables:** minimal re-encoder (one snapshot → `FeedMessage` → per-entity Kafka messages); Kafka topic setup with the §4.2 retention/compression settings; Spark streaming job decoding protobuf → Silver Delta table; DuckDB query over that Delta table; one Streamlit chart.
- **Measurements (feed §4 recalibration):** image sizes after build; Kafka bytes per replayed hour; Silver bytes per hour; checkpoint size; Spark time share spent reading the read-only mount (decides scale-run staging); VHDX size.
- **Tests:** E2E smoke (row counts landing → Kafka → Silver consistent); container restart does not duplicate Silver rows.
- **Exit:** skeleton runs from `python tasks.py skeleton`; `results/storage-calibration.json` projects steady usage ≤ 25 GB (or the owner approves an adjusted window/target).

### S3 — Replay harness & canonical schemas
- **Goal:** deterministic, paced, real-data event stream — the fairness backbone.
- **Deliverables:** full re-encoder for trip updates + vehicle positions (alerts optional); per-entity messages keyed by `trip_id`/`vehicle_id`, headers (feed, snapshot timestamp, `source_file`); pacing by original timestamps × speed factor; **fault injection** (duplicates, lateness 0/30/120 s, outages) behind explicit labelled flags; canonical schemas (typed records, service-day, `>24:00` times); lineage emission (`source_file` → offsets).
- **Tests:** **round-trip fidelity** (archive rows → protobuf → decoded rows equal on all fields used by any BR); seeded determinism (same seed → identical byte stream and offsets); pacing accuracy; message size < broker limit; fault flags never enabled in BR/acceptance runs.
- **Exit:** replaying the golden window yields entity counts equal to the manifest-derived counts.

### S4 — DuckDB golden KPIs — host ★ highest algorithmic risk
- **Status (2026-09-26):** ✅ delivered in three rounds: **S4a** (foundation + BR1 + BR2), **S4b** (BR3, BR4, BR5, BR8, bus terminal arrivals), **S4c** (BR6, BR7). All core KPIs (BR1–BR8) have golden references.
  - **Data facts that shaped the rules** (measured): bus vehicle positions carry no `current_status` (all NULL) — only the next stop; bus trip updates carry absolute predicted times (no delay field); subway trip updates carry no `stop_sequence`; schedules contain times past 24:00 and bus `timepoint` flags.
  - **Stop-event rule:** inferred per reporting unit (bus `vehicle_id`; subway has no vehicle id and its `entity_id` is only a position within each snapshot, so the unit is the trip). Observed arrival = prediction in the last snapshot that still listed the stop (numeric `arg_max` with a total order → deterministic). Statuses `passed`, `terminal`, `unconfirmed`, `implausible` (prediction > 180 s ahead when dropped), `stale` (prediction > 90 s in the past while listed = timetable echo).
  - **KPI events:** only `passed` events at **intermediate** scheduled stops; origin stops (departures, timetable echo: 94 % of subway origin events have exactly 0 s delay) and terminal stops (the rule measured when the trip left the feed: median +453–471 s vs ≈ +120 s elsewhere) are excluded and reported in `end_of_trip_summary` (BR7 evidence). One row per scheduled trip-stop; a trip-stop observed by more than one vehicle or real-time id is **ambiguous** and excluded from KPIs (owner decision: picking the first passage biased delays early), reported in `ambiguous_summary` (bus 1.4–1.9 % of trip-stops; 29–32 % of bus trips are reported by more than one vehicle).
  - **Trip matching:** bus exact (unique key per service day) ≈ 99.3 %; subway suffix + route/direction tiers ≈ 88–89 %; the rest labelled `unscheduled`. NYCT labels a trip that starts after midnight (id origin ≥ 24:00) with the calendar date, not its service day; it is shifted back one day before matching (S4b fix: 1,695 subway events had been matched to the wrong day, ≈ −24 h; `delay_sanity_summary` now guards this, 0 events off by > 6 h).
  - **Golden window results (2026-09-22/23), stop-level −1/+5 min band, intermediate stops:** bus on-time 46.9–47.4 % (timepoints 47.5–48.0 %; 21–22 % early, 31–32 % late, median +119–125 s); subway 67.5–69.0 % (after the service-day fix); bus headways regular ≈ 31 %, bunched ≈ 10 %; subway regular ≈ 44–46 %, bunched < 1 %. Stop-level measures, not MTA's official indicators.
  - **S4b rules (owner decisions):**
    - *BR3:* each scheduled trip on a route the feed carries is `delivered` (≥ 50 % of intermediate stops passed), `unknown` (outside snapshot coverage or overlapping a > 300 s feed gap), `missing` (never reported), `not_run` (reported but never seen moving: no stop passed, no last-stop arrival) or `partial`. Results: bus missing 2.4 %, not delivered (missing + not_run) 5.6–6.7 %; subway missing 3.4–4.3 %, not delivered 10.2–12.4 % (inflated by the ≈ 11 % of subway real-time trips that match no timetable trip). No feed gap > 300 s in the window.
    - *BR4:* arrival-to-arrival segments between consecutive KPI events of one trip **and one vehicle** (a vehicle change breaks the chain); delay = delay inherited at the vehicle's first observed stop + segment excesses, exact in integer seconds (0 mismatches). Dwell and running time cannot be separated (no departures or stopped-at status in this feed). Bus: mean inherited ≈ 180–197 s, gained along the route ≈ 177–206 s.
    - *BR5:* route and route-hour on-time share with a trip-level Poisson bootstrap (200 resamples; weights from md5 of seed, resample and trip, so other engines reproduce them exactly), percentile CI and rank intervals; sufficient = ≥ 10 events and ≥ 5 trips. The independent Python recomputation of the CI matches the SQL. Subway ranking: 1 (91.5 %) > 6 > 6X > 7 > 4 > 3 > 5 > 2 (47.0 %).
    - *BR8:* route-stop-hour reliability (events, on-time share, Wilson 95 % interval, p50/p90 delay), pooled over the window; identical counts to the BR1 events in every cell. 28 % of bus cells and 66 % of subway cells reach 10 events.
    - *Terminal arrivals (bus):* first vehicle position within 50 m of the last stop after the vehicle's last passed stop; separate `terminals` scope (all-stop figures unchanged). Measured for 66–68 % of trips; on time 37 %, median +195–204 s.
    - *Headways:* passages now include ambiguous trip-stops and unscheduled trips (no artificial gaps), never pair a vehicle with itself, and use a reference built from the same kind of scheduled stops.
  - **S4c rules (owner decisions):**
    - *BR6 early warning:* one decision per trip and vehicle, at the first KPI stop past the middle of the route that has a later KPI stop. Late: delay + 0.5 × trend × remaining scheduled time > 300 s (baseline: already > 300 s late). Bunched: headway ≤ 0.5 × scheduled reference (baseline: already bunched). Rules fixed on 09-22 only (small sweep recorded in `11_early_warning.sql`); **target declared before computing 09-23: beat the baseline on F1 with precision ≥ 0.6.** Held-out 09-23: bus late F1 0.788 vs 0.772 (P 0.83) ✅; bus bunched 0.646 vs 0.491 (P 0.80) ✅; subway late 0.663 vs 0.596 (P 0.71) ✅; subway bunched 0.230 vs 0.114 but P 0.18 ❌ (predicted from the dev day: 94–137 bunched outcomes per day). The decision population uses whole-day knowledge (a later KPI stop must exist), so absolute precision is optimistic for live use; rule and baseline share it.
    - *BR7 feed quality:* 12 metrics with declared thresholds (`feed_quality_thresholds`); conformance score = % of applicable checks passed per feed and day; a feed with no data fails every check. Both days: bus vehicle positions 100, bus trip updates 87.5 (not_run 3.2–4.2 %), subway trip updates 62.5 (not_run 6.7–8.0 %, stuck entries 6.3–8.7 %, unmatched trips 10.9–11.6 %). ~2.7 k real GPS jumps per day (median ≈ 1 km) listed in `position_jumps`. The snapshot-loss check was revised after seeing the development day: a header-timestamp definition flagged normal publication jitter, so loss is measured on the archive's fetch times (`missed_poll_share`).
  - **Evidence:** 23 golden tests (two hand-built service days) run the real SQL; S4a: 11 tests on a hand-computed synthetic service day (band edges ±1 s, two vehicles on one trip, real subway id semantics, all headway classes, DST fall/spring, byte-identical re-run); 7 hand-checked real events (`golden/hand-checks.json`); bus vehicle-position cross-check agrees on **96.0 %** of events (same AVL source, so it validates the inference rule, not the sensor). **Two full real runs are byte-identical.** Known limitation: inferred arrival runs ~15–30 s after the true passage.
  - **Reviewed twice (S4a):** the first review found non-determinism (merged vehicles, untied `arg_max`), origin/terminal bias, non-unique matching and weak tests; the re-review confirmed these resolved on real data and raised the multi-vehicle early bias (→ ambiguity rule) and a cross-check ordering tie (fixed).
  - **S4b review:** no critical or determinism defects; fixed: BR3 phantom trips (→ `not_run`), segments across a vehicle change, zero-width CIs for few-trip cells (→ ≥ 5 trips), headway reference vs short-turn stops, stale double counts, stop coordinates from one row. S4b tests cover loop stops, calendar add/remove exceptions, a Saturday-only service, stale/terminal/ratio/outage edges, subway trips starting at 23:59 and 25:07, vehicle hand-overs and skipped stops. Two full real runs are byte-identical.
  - **S4c review:** no critical defects or feature leakage; dev-day figures reproduced. Fixed: missing feeds and zero counts dropping checks, one-row fix positions and consistent day attribution, bunching tests unable to tell rule from baseline (route B band cases), comments on knowledge time. The feed-quality step no longer rescans all raw rows (425 s → ≈ 270 s).
  - **Open (for S5 freeze):** `position_jumps` also lists jumps from the neighbouring days of the archive partitions read (scores use the golden days only) — restrict to service days at the freeze. DuckDB `//` truncates toward zero, so a passage before the service day's midnight would get hour 0 instead of −1 (none observed). Subway stuck entries (median ≈ 46 min) are reported as feed quality (BR7), not corrected.
  - Run: `python tasks.py golden` (≈ 14–15 min, DuckDB 14 GB / 8 threads; heaviest steps: stop events ≈ 150–200 s, feed quality ≈ 270 s); outputs in `<data root>/golden/<window>/`, summary + checksums in `golden/`.
- **Goal:** define every core KPI's semantics as independent SQL on landing Parquet.
- **Deliverables:** SQL for dedup; **stop-event inference** (trip updates: last prediction before a stop leaves the update list; vehicle positions: `STOPPED_AT` / stop-sequence advance); schedule join with service-day logic; BR1 OTP; BR2 headway/bunching; BR3 missing trips; BR4 segment times + attribution; BR5 scorecard + bootstrap CI; BR6 rule-based early-warning labels; BR7 feed-quality metrics; BR8 per-stop reliability.
- **Tests:** hand-checked spot samples (documented); invariants (conservation, no unknown `trip_id`, bbox, no pre-service timestamps); edge cases (DST, `>24:00`, missing/duplicate snapshots, trip ID churn).
- **Exit:** all core KPIs computed on the golden window, matching hand-checked values within the declared tolerance.

### S5 — Golden freeze & correctness harness — host
- **Status (2026-09-27):** ✅ **dataset + query freeze done** (week-6 milestone). Two full golden runs byte-identical (tables and query answers); `python tasks.py golden-check` on the frozen outputs: 0 failures.
  - **Freeze (owner decision):** full Parquet stays in `<data root>/golden/20260922_20260923/` (reproducible from the manifest-pinned landing data by `tasks.py golden`, ≈ 8–15 min); git holds the checksum of every file (`golden/checksums.json`), byte copies of all but the three large tables (`golden/tables/`, 28 files ≈ 12 MB; `stop_events`, `headways`, `segments` ≈ 90 % of the output stay out) and the 25 frozen query answers (`golden/queries/` + checksums).
  - **Tolerance policy (owner decision, `golden/tolerance.json`):** rows matched on declared keys per table; exact for keys, counts, classes, flags, integer seconds and discrete quantiles; floats within 1e-4 absolute; the per-route mean delays (rounded to 0.1 s) within one rounding step, 0.1 s (owner chose one step after the review showed 0.05 s was effectively exact); a one-step difference at a tolerance equal to the step is accepted (epsilon 1e-9). Engines are compared after the golden window is fully processed (streaming jobs once drained).
  - **Harness:** `compare.py` (keyed tables and sorted query answers; missing / extra / duplicate rows, missing columns, NULL vs value, float tolerance), `properties.py` (13 invariants; NULL counts as a violation), `suite.py` (the 25 queries), `harness.py` + `tasks.py golden-check [--tables DIR]` (checksum mode for golden itself; table comparison for an engine's exported tables; then invariants and the query suite; one failing item never aborts the report). 23 harness tests, including a corrupted engine result that fails the table, invariant and query checks, and a missing table that fails only its own items.
  - **25-query suite (owner-approved):** 8 aggregations, 7 window-function, 8 join, 2 time-travel (Q24/Q25: the Delta version holding only the first service day = a date filter; engines without time travel report N/A). Runs in ≈ 3 s on DuckDB over the golden tables.
  - **Open for S9 (native execution of the suite):** the harness runs the queries in DuckDB over an engine's tables; running them natively needs per-engine translations and checks: ClickHouse `round` uses banker's rounding on exact binary ties and has no `WITHIN GROUP` (`quantileExactLow` for `percentile_disc`), no correlated `NOT EXISTS` (Q23 → anti-join); Spark computes `* 1.0` in DECIMAL and needs ≥ 3.5 for correct `percentile_disc`. Answers are compared after sorting, so NULL ordering does not matter.
- **Goal:** freeze reference answers and the query suite.
- **Deliverables:** frozen golden results (Parquet in `golden/` + checksums in Git); tolerance policy; reusable property-test library; **25-query Axis B suite** with golden answers; `python tasks.py golden`.
- **Tests:** byte-reproducible golden re-run; suite executes on DuckDB.
- **Exit:** **dataset + query freeze (end of week 6)**; golden checksums committed.

### S6 — Spark Silver — Docker (`spark`)
- **Goal:** production Silver layer from the replayed stream (and batch from landing for history).
- **Deliverables:** protobuf decode; watermarking; dedup; stop-event inference (same rules as S4, independently implemented); schedule join; teleport/outlier suppression; quality gates → dead-letter table; Silver tables (`silver.vehicle_positions`, `silver.stop_events`, `silver.trip_predictions_sampled` for BR6, `silver.feed_snapshots` for BR7); `meta.ingest_log`; partitioning by `service_date`.
- **Tests:** Silver intermediates vs golden intermediates; conservation `in = out + late_dropped + dead_lettered`; idempotent re-run (no duplicates after restart); schema-enforcement test.
- **Exit:** Silver for the golden window matches golden intermediates within tolerance.

### S7 — Spark Gold BR1–BR8 + Delta maintenance — Docker (`spark`)
- **Goal:** all core KPIs, streaming where freshness matters (BR1, BR2, BR6, BR7) and batch elsewhere (BR3, BR4, BR5, BR8), one code path.
- **Deliverables:** Gold tables per BR; **benchmark mode** emitting W1/W2 results to `kpi.spark.*` Kafka topics; checkpointing; `OPTIMIZE`/`VACUUM` job (time-travel demo table exempt until the demo is recorded); Gold exports to `exports/`.
- **Tests:** Gold vs golden per BR; late-event scenarios 0/30/120 s (labelled fault runs); restart recovery after `kill -9` (time-to-resume); **Delta time-travel re-read of a corrected late arrival**; duplicate idempotency.
- **Exit:** all BR1–BR8 Gold outputs match golden within tolerance; recovery under declared SLO.

### S8 — Flink Axis A workload — Docker (`flink`)
- **Goal:** the mandatory alternative, on an identical workload.
- **Deliverables:** build `flink-py` image; PyFlink jobs for **W1** (1-min tumbling event-time delay stats per route/stop) and **W2** (keyed stateful headway per route/direction/stop), same watermark policy and inference rules as Spark; sink `kpi.flink.*`.
- **Tests:** parity vs golden and vs Spark on identical offsets; output-schema equivalence; fairness assertions (same topic/offsets, caps, pace).
- **Exit:** both arms produce comparable W1/W2 outputs; deviations explained.

### S9 — ClickHouse & Axis B — Docker (`clickhouse`)
- **Goal:** serving comparison B1 Spark SQL over Delta · B2 DuckDB over Delta · B3 ClickHouse.
- **Deliverables:** ClickHouse config with capped system logs; loader from Delta Gold/Silver; the 25 queries for each arm; optional zero-copy sub-arm (DuckDB `read_parquet` over Delta data files after `OPTIMIZE`+`VACUUM`).
- **Tests:** parity of all 25 queries vs golden on every arm; load/freshness timing captured.
- **Exit:** all arms return golden-equal results (or documented, explained differences).

### S10 — Benchmarks & phase cleanup — Docker
- **Goal:** evaluation evidence.
- **Deliverables:** fairness contract (published first); **Axis A** runs (latency p50/p95/p99 from Kafka append times, throughput knee, late-data correctness, recovery, memory) → then **remove Flink image/state**; **Axis B** runs (cold/warm latency, freshness, footprint, compaction effect) → then **drop ClickHouse data/image**; **real-data scaling** (1/3/7-day slices) of Silver building in Spark; raw CSVs + plotting scripts in `results/`; post-phase compaction.
- **Tests:** ≥3 runs with spread; counterbalanced order; idle-host check; input checksums identical across arms; "what we did not test" declared.
- **Exit:** results reproducible from committed CSVs; storage log shows return to ≤ 25 GB steady.

### S11 — Application — host dev + Docker (`app`)
- **Goal:** demonstrate data exploitation per BR.
- **Deliverables:** Streamlit app: U1 reliability console, U2 diagnostics, U3/U4 scorecards and trends, U5 departure confidence, U6 feed health, U7 Hanoi map; data-access layer over DuckDB (Delta + Spatial). Development starts from golden/Gold exports on the host; integration reads the live `lakehouse` volume in the `app` profile.
- **Tests:** data-access unit tests; UI smoke tests; **per-BR acceptance tests on real data** (§6.3); time-to-insight task timings.
- **Exit:** every core BR (BR1–BR8) demonstrable in-app with recorded evidence.

### S12 — E2E, reproducibility & evaluation packaging — Docker
- **Deliverables:** `python tasks.py demo` (replay → Silver/Gold → app); evaluation report (correctness, performance, exploitation); reproducibility manifest (image digests, versions, host spec, caps); demo recording.
- **Tests:** clean clone on the host → `python tasks.py fetch` then `python tasks.py demo`; determinism re-run; artifact checklist.
- **Exit:** E2E passes from a clean clone; evaluation chapter complete.

### S13 — Desirable / optional
- **BR9** corridor history (batch path, subway group by default); **BR10** weather join; **BR11** Hanoi static coverage (DuckDB Spatial); optional extras from `PROJECT_PLAN.md` §20 (SeaweedFS, PostGIS, Metabase, live polling) only if the core is complete and the storage log allows.
- **Tests:** parity with core static handling; GTFS validity; licence attribution (ODbL, CC-BY).

### S14 — Submission artifacts — host
- Final report PDF, slide PDF, 20–30 min video, runnable product — **all named with the group ID**.

---

## 6. Testing & validation strategy

### 6.1 Layers

| Layer | Validates | Runs | Where |
|---|---|---|---|
| **L1 Unit** | re-encoder, parsers, SQL helpers, app data access | every commit | host / CI |
| **L2 Schema/contract** | canonical schemas, protobuf round trip | every commit | host / CI |
| **L3 Property/invariant** | conservation, bbox, no-orphan ids, determinism | every commit | host / CI |
| **L4 Golden** | DuckDB golden reproducibility | every commit (golden window) | host / CI |
| **L5 Integration** | Kafka round trip, Spark→Delta, Flink→Kafka, ClickHouse load | PR touching engines + stage gates | Docker (host or CI runner) |
| **L6 Performance** | latency, throughput, recovery, footprint, scaling | S10 | Docker on the host only |
| **L7 Acceptance/E2E** | each BR demonstrable on real data | S11/S12 | Docker |
| **L8 Reproducibility** | clean-clone one-command run | S12 | Docker |

### 6.2 Correctness anchors
- **Golden** (S5) computed by an independent method on landing Parquet before any engine is benchmarked.
- **Conservation:** `events_in == events_out + late_dropped + dead_lettered` (exact).
- **Round trip:** archive rows → protobuf → decoded rows equal on all used fields.
- **Determinism:** re-run → byte-identical output; corrected late arrival reproducible via Delta time travel.
- **Parity:** Spark, Flink (W1/W2) and all Axis B arms equal golden within tolerance, or the difference is explained.

### 6.3 Per-BR acceptance (real data only)

| BR | Automated acceptance test | Manual demo |
|---|---|---|
| BR1 OTP | Gold OTP == golden on a real sample day | scorecard values match |
| BR2 bunching | on a **real day where the golden run detected bunching**, Gold pairs == golden pairs | alert list/map shows the pair |
| BR3 missing trips | scheduled − observed == detected list == golden | gap report renders |
| BR4 travel time/attribution | attribution components sum to total delay; distribution == golden | chart per route |
| BR5 scorecard + CI | Gold CI == DuckDB-recomputed CI (same seed); ranking stable across resamples | ranking table with CI |
| BR6 early warning | precision/recall on a held-out real day ≥ declared target | warning list updates during replay |
| BR7 feed quality | Gold metrics == independent DuckDB checks on landing data | feed console shows a real gap/jump |
| BR8 rider explorer | parity with BR1 for the same stop/hour | stop-level confidence shown |

Injected faults (R3) appear only in L1–L3 unit tests and labelled robustness runs, **never** in this table.

### 6.4 Data-engineering quality gates (fail the build)
- No result row references a `trip_id` absent from the applicable GTFS static version.
- Coordinates within the service bbox; timestamps ≥ service start.
- Landing files immutable (checksums unchanged); Silver/Gold writes idempotent.
- Every BR result traces to landing files via the lineage table.
- No fault-injection flag set in any BR/acceptance run.

---

## 7. Quality gates & CI

| Gate | Trigger | Content | Where |
|---|---|---|---|
| **G0 pre-commit** | local commit | ruff, mypy, L1–L3 | host |
| **G1 PR fast** | every PR | lint + L1–L4 | CI (no Docker services) |
| **G2 integration** | PR touching engines/compose; nightly optional | L5 smoke with a 1-hour slice | CI runner Docker or the host |
| **G3 stage exit** | end of each stage | stage exit criteria (§5) + storage log entry | per stage |
| **G4 benchmark** | S10 | L6 + fairness contract | host only |
| **G5 release** | S12 | clean-clone E2E + reproducibility manifest | host |

**Branch policy:** feature branch → PR → review by ≥1 other member → merge to `main`; `main` always `python tasks.py check` green.

---

## 8. Dependency graph

```mermaid
flowchart LR
  S0["S0 Prereqs + foundations"] --> S1["S1 Landing data (host)"]
  S0 --> S2
  S1 --> S2["S2 Walking skeleton<br/>+ storage calibration"]
  S1 --> S4["S4 DuckDB golden ★ (host)"]
  S2 --> S3["S3 Replay harness"]
  S4 --> S5["S5 Golden + query freeze"]
  S3 --> S6["S6 Spark Silver"]
  S5 --> S6
  S6 --> S7["S7 Spark Gold BR1–BR8"]
  S3 --> S8["S8 Flink Axis A"]
  S5 --> S8
  S7 --> S9["S9 ClickHouse + Axis B"]
  S7 --> S10["S10 Benchmarks + cleanup"]
  S8 --> S10
  S9 --> S10
  S5 --> S11["S11 App (dev on exports)"]
  S7 --> S11
  S10 --> S12["S12 E2E + evaluation"]
  S11 --> S12
  S7 --> S13["S13 Desirable/optional"]
  S12 --> S14["S14 Submission"]
  S13 --> S14
```

**Critical path:** S0 → S1 → S2 → S3 → S6 → S7 → S9 → S10 → S12 → S14 (S4→S5 must finish by week 6 to join at S6).
**Parallel tracks:** S4 golden (host) ‖ S2/S3 (Docker); S8 Flink ‖ S7 once S3+S5 are done; S11 app dev from week 6 on exports.

---

## 9. Mapping to roadmap & ownership

| Roadmap phase (`PROJECT_PLAN.md` §17.1) | Stages | Weeks |
|---|---|---|
| P0 Foundation | S0, S1, S2 | 1–3 |
| P1 Replay + golden | S3, S4, S5 | 3–6 |
| P2 Production pipeline | S6, S7 | 6–9 |
| P3 Alternatives + benchmarks | S8, S9, S10 | 8–11 |
| P4 Application | S11 | 6–12 |
| P5 Evaluation + hardening | S12, S13 | 12–13 |
| P6 Submission | S14 | 14–15 |

| Member | Stage ownership | Primary BRs |
|---|---|---|
| M1 | S1, S3 (landing + replay harness) | BR3, BR7 |
| M2 | S2 (lead), S6, S7 (Spark) | BR1, BR2, BR6 |
| M3 | S8, S9, S10 (Flink, ClickHouse, shared benchmark harness) | BR4, BR5 |
| M4 | S4, S5, S11 (golden, correctness, app) | BR8, BR9 |
| All | S0, S12, S13, S14; report, slides, video | — |

BR ownership = end-to-end responsibility (golden SQL review, acceptance test, demo script), regardless of which stage implements the engine code.

---

## 10. Risks, gates & rollback

| Risk | Stage | Mitigation |
|---|---|---|
| Version/connector mismatch (Spark–Delta–Kafka, PyFlink–Kafka) | S2, S8 | Walking skeleton; pinned pairs; jars baked into images |
| Stop-event inference wrong | S4, S6 | Golden + hand-checked samples; same documented rules in both implementations |
| Static schedule version missing for window dates | S1 | Gate: move window inside one static version; subway versions archived |
| Archive unavailable later | S1 | Early download with checksums; fallback agencies in the same archive |
| Docker usage exceeds budget | S2+ | S2 calibration gate; §4 controls; weekly storage log; soft guard `python tasks.py storage-check` (warn 25 GB / block 30 GB) |
| Non-sparse disk image keeps peaks | S10 | Compaction at phase exit; peaks only in scheduled windows |
| Unfair benchmark | S8–S10 | Shared harness; identical offsets; append-time latency; idle-host check |
| PyFlink as a strawman | S8 | Identical logic and watermark policy; tuning symmetric and documented |
| Scope creep | any | S13 strictly after core; storage log must allow extras |
| Single-host failure | any | Git remote; manifest re-fetch; committed results; rebuildable engine zone |

**Rollback stance:** landing is immutable and re-fetchable; golden is versioned; engine-zone state is rebuildable from
landing + Git. A failed stage never invalidates earlier artifacts.

---

## 11. Unresolved questions

1. **Exact core window dates** — chosen in S1 inside a single MTA Bus static version if historical versions are unavailable.
2. **Corridor for BR9** — default subway group; confirm after S1 measurements.
3. **Scale-run staging** — decided by S2's mount-read measurement (§4.3).
4. **CI host** — GitHub Actions for G1 (and optionally G2) vs local-only.
5. **BR11 scope** — coverage map only, or accessibility metrics too.
6. **Group ID** for artifact naming (S14).
