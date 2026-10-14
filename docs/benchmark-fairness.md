# Benchmark fairness contract (S10)

This contract fixes how the two comparison axes and the scaling curve are measured. It was committed before the first measured run. Every run report records the commit of this file, and any deviation is written into the results, not edited here.

## Host and common rules

- **One machine.** ASUS TUF F15, i7-12700H (14 cores / 20 threads), 31.6 GB RAM, Windows 11, Docker Desktop (WSL2 VM: 20 CPUs, 17.6 GiB). Image digests are pinned in `docker/versions.env`.
- **Only the arm under test runs.** Before each run the harness records `docker ps`. Allowed containers per axis are listed below; anything else fails the run.
- **Cold start per run.** Each run starts the engine fresh. Axis B also drops the Linux page cache in the Docker VM before a cold pass (`echo 3 > /proc/sys/vm/drop_caches` from a privileged helper container), which is equal for every arm.
- **Three or more runs** per measured configuration, reported as median with min and max. Percentiles inside a run are computed over all samples of that run.
- **Counterbalanced arm order.** Two arms alternate (A B, B A, A B). Three arms rotate (B1 B2 B3, B2 B3 B1, B3 B1 B2). The order is logged.
- **Same input.** Every arm reads the same bytes: the Axis A slice's checksum and offsets, or Axis B's single `lakehouse/axis_b` Delta copy (provenance in `results/axis-b-load.json`).
- **Same parallelism.** Spark `local[8]` (driver 6 GB), Flink parallelism 8 on one TaskManager with 8 slots, DuckDB `threads = 8`, ClickHouse `max_threads = 8`. Memory is otherwise left at each engine's defaults and recorded.
- **Raw data first.** Every sample is written to CSV under `results/benchmarks/`. Summaries and plots are produced only by `python tasks.py bench-report` from those CSVs.
- **Synthetic data only for labelled fault runs** (R3): injected lateness and duplicates. Everything else is real archived data.

## Axis A: Spark Structured Streaming vs Flink (W1, W2)

- **Input.** A contiguous slice of the Axis A passage stream (`exports/axis-a/golden/passages.parquet`, event-time order), starting at the first passage at or after 2026-09-22 07:00 New York time. A configuration with rate R and duration D uses the first R × D passages, followed by the end marker. Golden W1/W2 for the slice are computed by the frozen golden SQL (`axis_a_w1.sql`, `axis_a_w2.sql`) over exactly those passages, and every run's outputs are graded against them.
- **Producer.** One paced producer (rate R passages/s, in event-time order) runs in the tooling container for both arms. The engine starts first and is ready before the first passage is sent.
- **Engines.** Spark: processing-time trigger 10 s, `maxOffsetsPerTrigger` 100,000. Flink: checkpoint interval 10 s, at-least-once Kafka sink. Both use a 120 s event-time watermark and the shared W2 state step (`axis_a/headway_state.py`).
- **Allowed containers:** `kafka`, `spark` (producer, plus the Spark arm itself), and for the Flink arm `flink-jobmanager` and `flink-taskmanager`.
- **Latency** is the output record's Kafka append time minus the input record's Kafka append time. Both stamps come from one broker clock (`LogAppendTime`).
  - W2: each headway is matched to its input passage by `grp, service_date, route_id, stop_id, trip_key`.
  - W1: a window can be emitted once the watermark passes its end. Its reference time is the append time of the first input passage with event time ≥ window end + 120 s. Windows closed only by the end marker are excluded.
  - The first 30 s of producing are warm-up and excluded. Percentiles reported: p50, p95, p99.
- **Latency runs:** R = 200 passages/s (about 10× the stream's real-time rate), D = 300 s, 3 runs per engine.
- **Throughput knee:** R ∈ {500, 1000, 2000, 4000} passages/s, D = 120 s, 3 runs per rate and engine. A rate is sustained when W2 p95 latency ≤ 30 s and the last output arrives within 60 s of the last input. The knee is the highest sustained rate.
- **Late data (fault runs):** R = 200, D = 120 s. A deterministic 1 % of passages (chosen by key hash) are sent L seconds of event time late, for L ∈ {0, 30, 120}. Reported per run: missing or extra W1 windows and W2 headways against the slice golden, plus each engine's own late-drop counters.
- **Duplicates (fault run):** R = 200, D = 120 s. A deterministic 1 % of passages are sent twice. Reported: the W1 and W2 differences against the slice golden.
- **Recovery:** R = 200, D = 300 s. At 120 s the engine is killed with SIGKILL: the Spark driver process, or the Flink TaskManager container. The harness restarts it at once from its checkpoint. Reported: time from the kill to the first new output record, and output correctness after deduplication on key (duplicates counted).
- **Memory:** `docker stats` is sampled every 2 s during latency runs, and the peak per arm is reported. The Spark figure includes the producer sharing its container, about 0.1 GB; Flink's is JobManager plus TaskManager.

## Axis B: Spark SQL vs DuckDB vs ClickHouse (the frozen 25-query suite)

- **Input.** `lakehouse/axis_b` Delta tables (B1, B2). B3 is ClickHouse `MergeTree` tables loaded from the same Delta files. The query text and its adaptations are those of S9 (`axis_b/dialect.py`). ClickHouse answers 23 queries.
- **Allowed containers:** `spark` for B1 and B2, `clickhouse` for B3. Kafka is stopped.
- **Run.** Drop the caches, start the arm, run the suite once (cold), then run it 5 more times (warm). Each answer is checked against golden on the cold pass. 3 runs, arm order rotated.
- **Reported:** cold latency per query (median, min, max over runs), and warm p50 and p95 per query over the 15 warm samples. Wall time covers the query and the full transfer of its answer.
- **Freshness.** The time from a new service-day Delta commit of `stop_events` until q01 answers with it. For B1 and B2 that is a query of the latest version in an open session. For B3 it is the day's `INSERT … SELECT FROM deltaLakeLocal`, then q01. The commit time is measured once and reported separately. 3 runs.
- **Footprint and compression:** Delta table bytes (active files plus log) against ClickHouse `system.parts` (on disk, compressed, uncompressed).
- **`OPTIMIZE` effect:** file counts and warm latency for B1 and B2 before and after `OPTIMIZE` on the Axis B tables, 3 runs each.
- **Zero-copy sub-arm:** after `OPTIMIZE` and `VACUUM`, DuckDB `read_parquet` over the current data files, with no Delta log. Time travel (q24, q25) is not applicable there.

## Real-data scaling (Silver build in Spark)

- 1-, 3- and 7-day real slices of the landing archive (from 2026-09-17), each replayed once into Kafka under its own topic prefix (replay report with counts).
- The Silver build (`silver_ingest`, all three feeds) runs 3 times per slice into a scratch lakehouse with fresh checkpoints. Reported: wall time, input messages, output rows and rows per second.
- Allowed containers: `kafka`, `spark`.

## Not tested (declared in advance)

Multi-node clusters, network-attached storage, failure of Kafka itself, exactly-once sinks, cloud object stores, concurrent query load (Axis B runs one query at a time), and any rate above the knee search grid.
