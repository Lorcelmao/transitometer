# Benchmark results (S10)

Measured under the [fairness contract](benchmark-fairness.md), committed (1d35e18) before the first measured run. Every row of every raw CSV records that commit. Raw samples are in `results/benchmarks/*.csv`; the tables below are copied from `results/benchmarks/summary/*.csv`, which `python tasks.py bench-report` rebuilds from the raw CSVs alone, together with the charts in `results/benchmarks/charts/`. A figure "per run" is the median over runs with min and max; percentiles are over all samples of one run. One laptop: i7-12700H, 31.6 GB RAM, Docker Desktop on WSL2 (20 CPUs, 17.6 GiB).

Every measured run was also graded for correctness. All Axis A runs equal the slice golden except the labelled duplicate runs (below), and every Axis B cold pass equals the golden answers.

## Headlines

| Question | Answer |
|---|---|
| Processing latency (200 passages/s) | Flink W1 p95 0.33 s, W2 p95 21.4 s; Spark W1 p95 22.6 s, W2 p95 40.2 s |
| Throughput knee (W2 p95 ≤ 30 s, drained within 60 s) | Flink: 1,000/s in every run, 2,000/s in 2 of 3; Spark: no rate in the grid |
| Recovery after SIGKILL | Spark 13.1 s, no duplicate output rows in any run; Flink 17.5 s, about 2,500 duplicate output rows (at-least-once sink); both equal to golden after deduplication |
| Peak memory | Spark 3.4 GiB, Flink 6.8 GiB (JobManager + TaskManager) |
| Serving the 25-query suite (warm pass) | DuckDB 2.66 s, ClickHouse 3.00 s (23 queries), Spark SQL 33.6 s |
| Freshness of a new service day | DuckDB 0.31 s, ClickHouse 0.73 s, Spark SQL 1.66 s, after a 3.16 s Delta commit |
| Silver build scaling | about 20,000 Kafka messages/s at both 1 and 3 days: build time grows linearly with input |

## Axis A: Spark Structured Streaming vs Flink

Input: the Axis A passage stream from 2026-09-22 07:00 New York, sent by one paced producer. The producer reached its target rate in every run and was never more than 0.04 s behind schedule. Latency is output append time minus input append time on the broker clock.

**Latency at 200 passages/s** (D = 300 s, 3 runs; `summary/axis_a_latency.csv`)

| Engine | W1 p50 / p95 / p99 | W2 p50 / p95 / p99 | Last W2 output after last input | Sustained | Equal golden | Peak memory |
|---|---|---|---|---|---|---|
| Flink | 0.25 / 0.33 / 0.37 s | 19.0 / 21.4 / 22.3 s | 0.9 s | 3 / 3 | 3 / 3 | 6.82 GiB |
| Spark | 18.0 / 22.6 / 23.1 s | 35.1 / 40.2 / 41.1 s | 15.7 s | 0 / 3 | 3 / 3 | 3.39 GiB |

W2 latency is mostly the event-time watermark: a headway is released only when the 120 s watermark passes its passage, so its latency is how long the stream takes to advance 120 s of event time. At a higher input rate event time advances faster and that wait shrinks, which is why Flink's W2 p95 falls from 21.4 s at 200/s to 8.6 s at 1,000/s. Spark adds its 10 s processing-time trigger, and its watermark only moves between micro-batches, so Spark's W2 p95 never comes under the 30 s target, even at the lowest rate.

**Throughput knee** (D = 120 s, 3 runs per rate; `summary/axis_a_knee.csv`, chart `charts/axis_a_knee.html`)

| Rate (passages/s) | Flink W2 p95 (min–max) | Flink drain | Flink sustained | Spark W2 p95 (min–max) | Spark drain | Spark sustained |
|---|---|---|---|---|---|---|
| 500 | 10.6 s (9.7–11.4) | 1.2 s | 3 / 3 | 33.4 s (33.4–33.5) | 20.3 s | 0 / 3 |
| 1,000 | 8.6 s (8.0–8.9) | 2.4 s | 3 / 3 | 55.7 s (49.9–56.6) | 34.9 s | 0 / 3 |
| 2,000 | 25.2 s (25.2–32.8) | 21.9 s | 2 / 3 | 66.4 s (66.1–67.3) | 44.1 s | 0 / 3 |
| 4,000 | 149.4 s (140.6–153.8) | 153.7 s | 0 / 3 | 68.3 s (67.7–69.2) | 48.9 s | 0 / 3 |

All 24 runs equal the slice golden. Flink's W1 (SQL windows) stays at about 0.3 s p95 at every rate; its W2 (a Python keyed process function) falls behind between 2,000/s and 4,000/s. Spark's W1 p95 rises from 27 s at 500/s to 48 s at 4,000/s, and its W2 levels off at about 68 s.

**Late data** (R = 200, D = 120 s; 1 % of passages, 223, sent L seconds of event time late; `summary/axis_a_late.csv`)

Every run at L = 0, 30 and 120 s equals the slice golden on both engines: no missing or extra W1 windows or W2 headways, and Spark's late-drop counter is 0 in every run. The grid stops at the watermark delay: a passage sent exactly 120 s late sits on the watermark, and late means strictly behind it, so no setting made either engine drop data. W2 p95 is unchanged by lateness (Flink about 20 s, Spark 40 to 43 s).

**Duplicates** (R = 200, D = 120 s; 223 passages sent twice; `summary/axis_a_dup.csv`)

W2 equals the golden on both engines after the grader's deduplication on output keys. W1 has 459 windows whose aggregates differ from the golden, with no missing or extra windows, identical on Spark and Flink in all 6 runs: neither engine deduplicates its input, so the repeated passages are counted twice in their windows.

**Recovery** (R = 200, D = 300 s, SIGKILL at 120 s: the Spark driver or the Flink TaskManager container; `summary/axis_a_recovery.csv`)

| Engine | Kill to first new output | Duplicate output rows | Equal golden after deduplication |
|---|---|---|---|
| Spark | 13.1 s (12.6–13.5) | 0 in every run | 3 / 3 |
| Flink | 17.5 s (15.8–18.2) | 2,508 (median) | 3 / 3 |

Spark's Kafka sink is at-least-once in general; these runs simply produced no duplicates. Flink's sink is configured at-least-once (contract), and it re-emits what it had sent since its last completed checkpoint.

## Axis B: Spark SQL vs DuckDB vs ClickHouse

The frozen 25-query suite over `lakehouse/axis_b`; B3 answers 23 queries (q24 and q25 read Delta versions, which `MergeTree` does not have). Cold is the first pass after dropping the page cache; warm is the mean of 5 further passes.

**Suite time** (3 runs; `summary/axis_b_suite.csv`; per-query cold and warm p50/p95 in `summary/axis_b_query_latency.csv`, chart `charts/axis_b_warm_p50.html`)

| Arm | Layout | Queries | Cold suite (min–max) | Warm suite (min–max) |
|---|---|---|---|---|
| B1 Spark SQL | Delta | 25 | 57.8 s (56.2–61.4) | 33.6 s (33.1–34.3) |
| B2 DuckDB | Delta | 25 | 3.04 s (2.97–3.10) | 2.66 s (2.64–3.54) |
| B3 ClickHouse | `MergeTree` | 23 | 3.29 s (3.13–3.57) | 3.00 s (2.68–3.12) |
| B1 Spark SQL | Delta after `OPTIMIZE` | 25 | 65.4 s (62.7–68.0) | 41.1 s (40.6–42.7) |
| B2 DuckDB | Delta after `OPTIMIZE` | 25 | 6.00 s (5.97–6.10) | 5.96 s (5.93–6.06) |
| B2z DuckDB | Parquet only, no Delta log | 23 | 5.43 s (5.39–5.54) | 5.44 s (5.37–5.54) |

- **Freshness** (`summary/axis_b_freshness.csv`): after the new day's Delta commit (3.16 s, measured once), q01 sees it in 1.66 s on Spark SQL and 0.31 s on DuckDB. ClickHouse needs 0.73 s, of which 0.70 s is the day's `INSERT … SELECT` from the Delta files.
- **Footprint** (`summary/axis_b_footprint.csv`): 9.94 M rows. Delta 134 MB in 104 files; ClickHouse 202 MB on disk in 24 parts. Against ClickHouse's uncompressed size (2.20 GB) that is 16.4 : 1 for Delta and 10.9 : 1 for ClickHouse.
- **`OPTIMIZE`** (`summary/axis_b_compaction.csv`): 43.2 s; 104 files became 11 (about one per table) and 133.6 MB became 128.5 MB. It made both Delta arms slower (warm Spark SQL 33.6 → 41.1 s, DuckDB 2.66 → 5.96 s). Our reading, not measured directly: these tables are small, and one file per table leaves the 8 threads fewer files to scan in parallel.
- **Zero-copy** (B2z vs optimized B2, the same files): reading the Parquet files without the Delta log saves about 0.5 s per suite pass.

## Real-data scaling: the Silver build in Spark

Slices of 1 and 3 archive days from 2026-09-17, each replayed once into its own topic prefix; `silver_ingest` (all three feeds) runs 3 times per slice from empty output and checkpoints (`summary/scaling.csv`, chart `charts/scaling.html`; bytes and replay reports in `scaling_runs.csv` and `scaling_replays.json`).

| Slice | Replay | Messages in | Rows out | Build time (min–max) | Messages/s | Silver output | Checkpoints |
|---|---|---|---|---|---|---|---|
| 1 day | 401 s | 17.52 M | 201.1 M | 861 s (849–863) | 20,300 | 1.99 GB | 2.94–3.14 GB |
| 3 days | 1,177 s | 47.45 M | 554.7 M | 2,249 s (2,209–2,353) | 21,100 | 5.48 GB | 4.49–4.95 GB |

Every run balanced (each Kafka message read is kept, dropped as a duplicate or as late, or dead-lettered), and the rows out are identical across the runs of a slice. Time grows linearly with input; the checkpoints grow much less than the input, because the deduplication state is bounded by the watermark.

## Deviations from the contract

- **7-day slice not run (as of 2026-10-29).** Measured 1- and 3-day bytes project a Docker peak of about 61 GB, above the 50 GB storage block, and about 5 hours. It can be added later with `python tasks.py bench-scaling --days 7 --allow-peak`; the 1- and 3-day rows are kept and the summaries rebuilt. Until then, the scaling claim rests on two points.
- **Flink readiness check.** The first full Axis A sweep stopped at the first Flink `late:30` run: the readiness check required every task to run, but a bounded source subtask with no Kafka partition (parallelism 8 over 6 partitions) finishes right after start. Ready now means every task runs or has finished (b760fff). The late-data scenario was then rerun from scratch; no measurement definition changed.
- **The knee depends on the rule.** The contract defines a sustained rate per run. At 2,000/s Flink sustained 2 of 3 runs, so its knee is 1,000/s when every run must pass and 2,000/s by the median.
- **Lateness never exceeded the watermark** (above), so late-data dropping was not exercised.
- **Peak memory** is sampled in every run; the figures above are from the latency runs, as the contract states. Spark's includes the producer in its container (about 0.1 GB).
- **Kafka topic deletion is deferred.** After the 3-day slice Kafka still held about 6 GB of the deleted `scale3` topics, because Kafka removes a deleted partition's files only after `file.delete.delay.ms` (60 s) and the harness stopped the broker at once. The harness now waits until no deleted partition remains.
- **Phase-scoped engines were removed** after their axis: ClickHouse (container, data volume, image) and Flink (containers, image, checkpoints). Re-running an axis rebuilds the Flink image from `docker/flink-py` and pulls ClickHouse again by its pinned digest.

## What we did not test

Declared in the contract: multi-node clusters, network-attached storage, failure of Kafka itself, exactly-once sinks, cloud object stores, concurrent query load, and rates above the knee grid (4,000 passages/s). Found or left out during the runs:

- lateness beyond the 120 s watermark, so the engines' late-data dropping;
- input deduplication in the engines (duplicates are passed through to W1);
- recovery from a Flink JobManager failure (only the TaskManager was killed);
- runs longer than 300 s, and other parallelism settings than 8;
- the 7-day scaling slice (unless it is added as above).

## Reproduce

```bash
python tasks.py bench-axis-b                                   # Axis B (needs the clickhouse profile)
python tasks.py bench-axis-a --scenarios latency knee late dup recovery --runs 3
python tasks.py bench-scaling --days 1 3                       # add 7 with --allow-peak
python tasks.py bench-report                                   # summaries and charts from the CSVs
```
