# Evaluation

Transitometer is evaluated on three questions: are its results correct, how does it perform against the alternatives, and can its users act on them. Every number below comes from a committed result file named next to it; the detail is in the linked documents. The golden window is the service days 22–23 September 2026 (UTC archive days 22–24).

## 1. Correctness

Correctness is judged against an independent reference: the same business rules written a second time in DuckDB SQL over the raw archive (the golden reference), frozen with SHA-256 checksums before the Spark pipeline was compared with it.

| Claim | Result | Evidence |
|---|---|---|
| The Kafka stream is the archive, complete and unaltered | 52,756,838 messages replayed, all acknowledged; read back = archive entity count for every feed; 60 of 60 sampled snapshots equal field for field | `results/replay-report.json`, `results/replay-verification.json` |
| Silver loses and invents nothing | Silver rows = archive rows (607,076,700) for every feed; 0 duplicates, 0 late, 0 dead-lettered; conservation balanced | `results/silver-ingest.json` |
| Spark Silver equals golden | 4 / 4 tables (`stop_events`: 2,955,606 rows) | `results/validation-silver.json` |
| Spark Gold equals golden, for every core requirement | 23 / 23 tables (BR1–BR8) | `results/validation-gold.json`, [BR acceptance](br-acceptance.md) |
| The golden reference is deterministic | two full runs byte-identical (tables and query answers) | `golden/checksums.json` |
| The alternative processing engine agrees (Axis A) | Spark and Flink: W1 2,919,421 / 2,919,421 windows, W2 2,956,930 / 2,956,930 headways | `results/validation-axis-a.json` |
| The alternative serving engines agree (Axis B) | Spark SQL 25 / 25 and DuckDB 25 / 25 queries; ClickHouse 23 / 23 (q24, q25 need Delta versions); 3 rows of q07 on exact rounding ties, accepted only by the tie rule | `results/validation-axis-b.json`, `golden/tolerance.json` |
| Benchmarks measure correct runs | every Axis A run graded against its slice golden (all equal except the labelled duplicate runs); every Axis B cold pass graded | [benchmark results](benchmark-results.md) |
| The code keeps these properties | 231 tests (unit, property and golden-rule tests) plus lint and type checks, on Python 3.10 and 3.12 in CI; the web site has Playwright parity and accessibility tests | `tasks.py check`, `.github/workflows/ci.yml` |

Rows are compared on their keys, with every other column equal; floats within the declared tolerance. The only exception to exact equality is the q07 rounding-tie rule, and each row it accepts is listed with its exact integer sum and count.

## 2. Performance

Measured on one laptop (i7-12700H, 31.6 GB RAM, Docker on WSL2) under a [fairness contract](benchmark-fairness.md) published before the first run: 3 runs per configuration, alternating arm order, only the arm under test running, identical input bytes. Medians of 3 runs; full tables, spreads and deviations in [benchmark results](benchmark-results.md).

**Pipeline on the golden window**

| Step | Time | Evidence |
|---|---|---|
| Replay into Kafka (3 feeds in parallel, unpaced) | 1,247 s | `results/replay-report.json` |
| Spark: stop events, timetable matching, statuses | 481.8 s | `results/silver-events.json` |
| Spark: Gold KPI tables (BR1–BR8) | 309.9 s | `results/gold-kpis.json` |
| DuckDB golden, all 12 steps | 892.1 s | `results/golden-run.json` |

**Processing: Spark Structured Streaming vs Flink (Axis A)**

| | Flink | Spark |
|---|---|---|
| W1 (1-minute windows) latency p95 at 200 passages/s | 0.33 s | 22.6 s |
| W2 (headway per passage) latency p95 at 200 passages/s | 21.4 s | 40.2 s |
| Highest rate meeting W2 p95 ≤ 30 s | 1,000/s in every run (2,000/s in 2 of 3) | none in the grid |
| Recovery after SIGKILL | 17.5 s, about 2,500 duplicate outputs (at-least-once sink) | 13.1 s, no duplicates observed |
| Peak memory | 6.8 GiB | 3.4 GiB |

W2's latency is dominated by the 120 s event-time watermark that a headway must wait for; Spark adds its 10 s trigger and moves its watermark only between micro-batches, so it never meets the 30 s target. Both engines handled late data up to the watermark without loss, and neither deduplicates repeated input.

**Serving: Spark SQL vs DuckDB vs ClickHouse (Axis B)**

| | Spark SQL | DuckDB | ClickHouse |
|---|---|---|---|
| Frozen query suite, warm pass | 33.6 s (25 queries) | 2.66 s (25) | 3.00 s (23) |
| Cold pass | 57.8 s | 3.04 s | 3.29 s |
| A new service day becomes queryable | 1.66 s | 0.31 s | 0.73 s (incl. 0.70 s load) |
| Storage of the 9.94 M rows | 134 MB (Delta) | 134 MB (Delta) | 202 MB |

`OPTIMIZE` (104 files into 11) made both Delta arms slower on these small tables (DuckDB 2.66 → 5.96 s).

**Scaling of the Silver build (Spark, real data)**

| Slice | Messages in | Build time | Throughput |
|---|---|---|---|
| 1 day | 17.5 M | 861 s | 20,300 messages/s |
| 3 days | 47.5 M | 2,249 s | 21,100 messages/s |

Build time grows linearly with input over these two points. The 7-day slice has not been run: from the measured bytes it would take about 5 hours and briefly raise Docker usage to about 61 GB, above the 50 GB storage cap.

## 3. Use of the data

The results reach their users through two frontends that share one view layer (`serve/views.py`), so every number, threshold and verdict is computed once; both are tested against one file of expected headline values (`showcase/contract/parity-expected.json`).

- **Analyst console** (Streamlit; local in Docker, or hosted at transitometer.streamlit.app on the validated snapshot): one page per requirement, BR1–BR8.
- **Public site** (Next.js static export at transitometer.vercel.app): the same findings as editorial pages, plus the evidence behind each number.
- Every core requirement is shown on real data in both, with screenshots: [BR acceptance](br-acceptance.md).
- The early-warning rules (BR6) were tuned on 22 September and tested on the held-out 23 September: precision 83 % ("ends late") and 80 % ("gets bunched") for buses, above the 60 % target and better than a naive baseline on F1.

## 4. Reproducibility

Every input is pinned in a file the code checks (data SHA-256s, image digests, package locks, golden checksums), and a fresh clone runs the end-to-end demo with the README's commands: [reproducibility](reproducibility.md).

## 5. Limits

- One machine, one node; no cloud storage, no network-attached storage, no Kafka failures.
- Two service days of golden reference; the scaling claim rests on 1- and 3-day slices.
- Late data was tested only up to the watermark; Flink recovery only for a TaskManager kill; runs of at most 300 s.
- Docker holds 29.2 GB in steady state, above the 25 GB target, because the validated golden-window state (Silver, the Kafka replay and a checkpoint, about 18 GB) is kept.
- The full list of what was not tested is in [benchmark results](benchmark-results.md#what-we-did-not-test).
