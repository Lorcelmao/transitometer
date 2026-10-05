# Data Engineering Technology Landscape — CO5173 Transportation Project

> **ERRATA / SUPERSEDED ASSUMPTION (2026-09-23, post-review).** Sections §7.1 ("Can a laptop run this?") and
> §7.3 ("Team-of-4 operating model") assumed **team hardware distributed across four laptops** and left the
> 16 GB vs 32 GB question open. **This is superseded.** The approved runtime is **ONE machine** — the
> designated development host (ASUS TUF F15; i7-12700H 14C/20T; 31.6 GB RAM; D: ~198 GB free; Docker Desktop
> 29.1.2) — with all heavy services run **sequentially via Docker Compose profiles**, and **Git** as the
> collaboration/distribution mechanism. Also binding: the core project uses **real** transportation data;
> synthetic data is supplementary only. The per-technology analysis below (selection, comparison design,
> benchmarking methodology) remains valid and is the basis for the plan; only the multi-machine/deployment
> framing and the synthetic-data assumption are corrected. Authoritative statements: `PROJECT_PLAN.md` §1.1,
> §1.2, §13.4, §17.4.

- **Course**: CO5173 Data Engineering — Sem 1, 2026-2027 (HCMUT, Vietnam)
- **Domain (assigned)**: Transportation
- **Team size**: 4 students, ~1 semester
- **Report type**: Technology research & comparison design (feeds `02-candidates` and `04-architecture`)
- **Research date**: 2026-09-23 (UTC+7)
- **Author**: Technical Analyst subagent
- **Companion doc**: the instructor's project requirements (course material, not published in this repository)

> Scope: This report evaluates the instructor's technology menu plus adjacent technologies,
> and proposes concrete, defensible comparison experiments. It does **not** pick the final
> business requirements — that is the team's decision (see §5, §8).

---

## Table of Contents

1. [How to read this report](#1-how-to-read-this-report)
2. [Executive summary & recommendation](#2-executive-summary--recommendation)
3. [Domain → workload framing (what the tech must actually do)](#3-domain--workload-framing-what-the-tech-must-actually-do)
4. [Technology landscape](#4-technology-landscape)
   - 4.1 [Data management](#41-data-management)
   - 4.2 [Data processing](#42-data-processing)
   - 4.3 [Supporting / platform layer](#43-supporting--platform-layer)
   - 4.4 [Master comparison matrix](#44-master-comparison-matrix)
5. [Proposed comparison experiments](#5-proposed-comparison-experiments)
6. [Benchmarking methodology](#6-benchmarking-methodology)
7. [Infrastructure reality check](#7-infrastructure-reality-check)
8. [Risks, anti-patterns, and unresolved questions](#8-risks-anti-patterns-and-unresolved-questions)
9. [References & verification log](#9-references--verification-log)

---

## 1. How to read this report

| Tag | Meaning |
|---|---|
| **VERIFIED (url)** | Claim traced to a source listed in §9. |
| **VENDOR CLAIM** | Source is a vendor's own benchmark or marketing. Directionally useful, never a neutral benchmark. Cite it as "vendor-reported". |
| **ASSUMPTION** | My engineering judgement / field experience, not source-backed. Treat as a hypothesis to validate. |
| **UNVERIFIED** | Recalled fact I could not confirm in this research pass. Verify before putting it on a slide. |

**Bias controls applied**: official docs and pricing pages weighted above blogs and vendor benchmark pages; conflicting free-tier numbers flagged rather than averaged; every "X is faster" claim from a vendor is marked as such.

---

## 2. Executive summary & recommendation

The project's hard constraint is *not* raw scale — it is **producing a fair, reproducible comparison with 4 people in one semester**. The instructor's rubric gives 4/10 to "Technology Content" and 1/10 to "Evaluation", but the real differentiator is C7 (required alternative solution) and C9 (>85% of evaluation criteria clearly defined). *Depth of one good comparison beats breadth of ten shallow ones.*

**Recommended stack shape — "local-first, one swappable engine axis":**

```
GTFS static (zip) ──┐
GTFS-RT (proto/json)│
Traffic sensors ────┤──► Kafka (KRaft, Docker)  ◄── replayable, seeded dataset
Socio-economic CSVs─┘         │
                              ├─► [PROCESSING AXIS]
                              │     primary:  Spark Structured Streaming (micro-batch)
                              │     alternative: Apache Flink (event-time, per-event)
                              │
                              ├─► [STORAGE AXIS]
                              │     primary:  Delta Lake on MinIO (lakehouse + Parquet)
                              │               queried by DuckDB / Trino
                              │     alternative: ClickHouse (columnar serving) or BigQuery (managed)
                              │
                              └─► [SERVING / APP]
                                    FastAPI or Streamlit + Metabase/Superset/Grafana

Static reference layers: PostGIS (+pgRouting) for GTFS + road network
Graph alternative:       Neo4j (Docker or Aura Free) for multimodal routing
Orchestration:           Airflow **or** cron/Make (dbt optional)
```

**Why this shape**

1. **Kafka is the shared substrate.** Every comparison reads the *same* topics, which is what makes alternatives comparable instead of merely different. Kafka is free, Docker-runnable, and on the instructor's processing menu (Kafka Streams) so it is "consistent with" the required technology list.
2. **One processing axis + one storage axis = 2 genuinely defensible alternatives** (satisfies "at least one", exceeds it for the bonus). This is the maximum a 4-person team can do well.
3. **Everything runs on a laptop** via Docker Compose, so the project survives weak campus/student internet, and cloud is an *optional* accelerator rather than a dependency. Cloud free tiers expire; laptops do not.
4. **Every component is a real industry tool**, so the report has production case studies to cite (not academic toys).

**Technology content requirement (>3 illustrative examples)**: satisfied by Kafka, Spark-SS, Flink, Delta/Iceberg, MinIO, ClickHouse, PostGIS, Neo4j — pick 3-4 to deep-dive and keep the rest as a landscape table (§4).

**Do NOT do this**: install 8 engines, demonstrate none of them properly, and benchmark nothing reproducibly. That is the single most common failure of this assignment.

---

## 3. Domain → workload framing (what the tech must actually do)

Technology choice is meaningless without the workload. For a transportation domain, the realistic data shapes are:

| # | Data artifact | Format / source | Volume (realistic, class project) | Character | Workload type |
|---|---|---|---|---|---|
| D1 | **GTFS static** (routes, trips, stops, stop_times, calendar) | CSV zip, from transit agency | 10-200 MB zipped; ~10^5-10^6 stop_time rows | Relational, slowly changing, small | Batch load, joins, routing graph build |
| D2 | **GTFS-Realtime** (TripUpdate = delays; VehiclePosition = lat/lon; Alerts) | Protobuf (feed spec) | 0.1-5 MB/poll; polled every 15-30 s per agency | Streaming, out-of-order, duplicates, late arrivals | Stream processing, event-time windows |
| D3 | **Traffic sensor / loop detector counts** | CSV/JSON API | 10^6-10^8 rows if historical | Append-only time-series, per-lane | Time-series ingest + OLAP aggregation |
| D4 | **Vehicle GPS / AVL** (from open feeds e.g. city open data) | JSON/CSV | 10^7-10^8 pings | High-frequency time-series, geospatial point | Stream ingest, geo aggregation |
| D5 | **Road network** (OSM extract) | PBF / shapefile | 0.5-2 GB for a city | Graph + geometry | Spatial indexing, shortest path |
| D6 | **Socio-demographic / zone stats** | CSV | MB-scale | Batch, stable | Dimensional modelling, joins |
| D7 | **Weather / events** (optional enrichment) | API | small | Batch/stream | Join enrichment |

**The three required evaluation axes map onto these workloads:**

- **Data correctness** → D1↔D2 join fidelity (does a computed delay match the agency's own TripUpdate?), dedup of D2, no-lost-events conservation checks on D4, spatial join correctness on D5.
- **Performance** → ingest throughput (events/s) for D2/D4, query latency for D3 analytics, routing latency for D5. Note: "Big Data context" here means *demonstrated scaling behaviour* (e.g., 10^7 synthetic rows), not real petabyte data. Generate synthetic data to scale up deterministically.
- **Application data-exploitation effectiveness** → the app must expose D1-D6 through the serving layer; measure time-to-insight, query coverage of business requirements, and freshness.

**Realistic scale check (important for honesty on the slides)**: a class project will hold **10^6-10^8 rows**, which is *medium* data. This is fine — say so explicitly, then show that the architecture *would* scale (add partitions/brokers/workers) and demonstrate it with a scaling experiment against synthetic data. Claiming "Big Data" with 50k rows is the fastest way to lose credibility.

**GTFS-Realtime is the key domain asset** — it is a real, published, protobuf spec with documented semantics for delays and vehicle positions, and it gives you genuine out-of-order/late-arriving events, which is exactly what makes an event-time comparison meaningful rather than synthetic theatre. **VERIFIED (https://gtfs.org/documentation/realtime/reference/)**

---

## 4. Technology landscape

Legend for the "Compare?" column: **★** = strong candidate for a same-problem-different-engine comparison; **~** = possible but weaker/secondary; **–** = poor comparison candidate (too different a problem, or too heavy).

### 4.1 Data management

#### 4.1.1 Cloud data warehouses (managed, columnar)

| | Redshift | BigQuery (+BigLake) | Synapse Analytics | Oracle "data lakehouse" |
|---|---|---|---|---|
| **What it is best at** | AWS-native columnar MPP warehouse; tight S3/Glue/IAM integration | Serverless columnar warehouse; BigLake unifies lake + warehouse; best-in-class zero-ops | Azure-native warehouse + Spark pools + Data Explorer; Microsoft-stack integration | Oracle Autonomous DW + Object Storage; strong enterprise SQL/PL-SQL |
| **Stream vs batch** | Both (Streaming Ingestion via Kinesis/MSK Firehose) | Both (Storage Write API, streaming inserts) | Both (via Event Hubs / Spark Structured Streaming) | Both (limited) |
| **OSS vs paid / 2026 free tier** | Paid. **Not in AWS Free Tier.** Free trial: ~2 months on a small config. **VERIFIED (https://aws.amazon.com/redshift/free-trial/, https://www.reddit.com/r/aws/comments/1ncisct/)** | Paid, but **always-free tier**: 1 TiB queries + 10 GiB storage / month; **BigQuery sandbox = no credit card needed**. **VERIFIED (https://cloud.google.com/free)** | Paid. Azure for Students $100 credit; Azure SQL has a separate always-free serverless offer (100k vCore-s/mo, 32 GB) but Synapse ≠ that offer. **VERIFIED (https://learn.microsoft.com/en-us/azure/azure-sql/database/free-offer)** | Paid (Oracle Free Tier has Always-Free Autonomous DB + 20 GB object storage). **UNVERIFIED specifics** |
| **Docker/local?** | No | No | No | No |
| **Cloud student credits** | AWS $100 + up to $100 earned = $200 max. **VERIFIED (https://aws.amazon.com/free/)** | $300/90-day welcome credit on top of always-free. **VERIFIED (https://cloud.google.com/free)** | Azure for Students = $100, no credit card, academic email. **VERIFIED (https://learn.microsoft.com/en-us/answers/questions/5837170/)** | Limited/unclear for VN students |
| **Ease for 4 students** | Medium — RPU-hours and cluster lifecycle are a cost trap | **High** — sandbox + SQL is the gentlest on-ramp; nothing to operate | Medium-Low — Fabric migration confusion; portal nags | Low |
| **Geo + time-series fit** | Geo: weak (no native geo type); TS: good via sort keys + date partitioning | Geo: `GEOGRAPHY` type + BigQuery GIS functions; TS: excellent partitioning + clustering | Geo: limited; TS: good in Data Explorer (KQL) | Geo: Oracle Spatial is strong (SDO_GEOMETRY); TS: adequate |
| **Ecosystem friction** | VPC/IAM/NAT complexity; egress cost; connection from laptop needs VPC config for some modes | Cost surprise if a query scans TBs; no local dev parity | **Synapse is no longer Microsoft's flagship analytics product** (Fabric is); a non-dismissible "migration readiness" banner now appears in the portal. No formal EOL announced. **VERIFIED (https://solv-systems.com/resources/fabric-vs-azure-synapse-2026, https://avantiico.com/azure-synapse-vs-fabric-comparison-difference/)** | Oracle tooling/licensing heavy |
| **Compare?** | ~ (managed warehouse vs local columnar is a fair *cost/ops* comparison) | ★ (fair scan-cost + latency comparison vs ClickHouse/DuckDB) | ~ (avoid: product-in-transition, weak payoff for the risk) | – |

**Take**: pick **BigQuery** if you want a managed warehouse in the comparison (best free tier, lowest ops, real GIS). **Avoid Synapse** — it is a product in strategic retreat (Fabric), which adds narrative risk to your report for no technical gain. Redshift is fine but strictly worse than BigQuery for a student team.

#### 4.1.2 Lakehouse formats & object storage (the self-hostable heart of the project)

| | MinIO | Delta Lake | Apache Iceberg | Apache Hudi |
|---|---|---|---|---|
| **Best at** | S3-compatible object store, self-hosted, single binary | Parquet + `_delta_log` transaction log; ACID, time travel, upsert/merge; deepest Spark integration | Open table format; **won the multi-engine/catalog war**; best cross-engine neutrality (Spark/Trino/Flink/DuckDB) | Ingest-optimised lakehouse with record-level indexing; strongest for high-frequency CDC upserts |
| **Stream vs batch** | Storage substrate | Both (Structured Streaming sink with exactly-once) | Both (Flink + Spark sinks) | Both (streaming upsert is its origin story) |
| **OSS/paid + free tier** | **Open source, AGPLv3**, free forever. **VERIFIED (https://min.io)** | Open source (Linux Foundation). Databricks-managed offering is paid. | Open source (Apache). Catalogs: Iceberg REST (free), AWS Glue, Nessie (free/OSS). | Open source (Apache) |
| **Docker/local** | **Yes** — one container, ~100 MB. Laptop-trivial. | Yes (library + MinIO) | Yes (library + MinIO + a catalog) | Yes (heavier; more concepts: copy-on-write vs merge-on-read, table types) |
| **Cloud managed** | Self-host only (or S3/GCS/Azure Blob instead) | Databricks, Azure | AWS (S3 Tables), GCP, Snowflake, Databricks, Trino | AWS (EMR), Onehouse (paid) |
| **Ease (4 students)** | **Very high** | **High** if using Spark | Medium — catalog choice adds a moving part | **Low-Medium** — most concepts to learn of the three |
| **Geo + TS fit** | N/A (storage) | Good: partition by date/zone; Z-ORDER on lat/lon; time travel is genuinely useful for "correctness after re-processing" evidence | Good; better hidden-partitioning | Good; indexing helps point lookups |
| **Friction** | Not S3 (no IAM, no per-object ACLs); fine for a project | Ties you to Spark/Databricks tooling more than Iceberg | Catalog setup (REST/Nessie/Hive MS) is the usual beginner wall | Smaller community; docs aimed at platform engineers |
| **Adoption signal (2026)** | S3-compatible APIs are the de-facto lake interface | **Largest single-vendor ecosystem**; strong on Databricks | **Consensus "winner" of the table-format war** for multi-engine/neutrality; Iceberg 1.7 adoption cited widely; Iceberg better on time-travel, Delta more efficient compaction in at least one comparative study. **VENDOR CLAIM / partial** **(https://www.onehouse.ai/blog/apache-hudi-vs-delta-lake-vs-apache-iceberg-lakehouse-feature-comparison, https://www.dremio.com/blog/comparison-of-data-lake-table-formats-apache-iceberg-apache-hudi-and-delta-lake/, https://amdatalakehouse.substack.com/p/lakehouse-table-formats-in-2026-iceberg)** | Crossed 1.0; database-grade indexing ambitions. **VENDOR CLAIM (https://amdatalakehouse.substack.com/p/lakehouse-table-formats-in-2026-iceberg)** |

**Take**: **MinIO + Delta Lake** is the lowest-friction self-hosted lakehouse and pairs natively with Spark Structured Streaming (which you are using anyway). If you want the report to look more 2026-current, use **Iceberg + Nessie** instead and compare *that* against Delta — but that is a third axis you probably cannot afford. Recommend: **Delta as primary, and mention Iceberg/Hudi in the landscape table with a justified rejection** (catalog overhead vs available time).

#### 4.1.3 Analytical / columnar serving stores

| | ClickHouse | DuckDB | Apache Druid | Trino (Presto) |
|---|---|---|---|---|
| **Best at** | High-cardinality columnar OLAP + real-time ingestion; sub-second aggregations on billions of rows | In-process analytics **in your Python process**; zero-infrastructure; queries Parquet on MinIO directly | Real-time OLAP with always-on ingestion + time-partitioned segments; good concurrency for dashboards | Federated distributed SQL across many sources (lake, RDBMS, Kafka) |
| **Stream vs batch** | Both — native Kafka engine + `MergeTree` | Batch (DuckDB 1.x has limited/experimental streaming; treat as batch) | Stream-native (Kafka indexing service) | Batch (federated queries) |
| **OSS/paid** | Apache-2.0, free. ClickHouse Cloud is paid (has a trial). | MIT, free. MotherDuck is paid. | Apache-2.0, free. Imply is paid. | Apache-2.0, free. Starburst is paid. |
| **Docker/local** | **Yes**, single container, very light | **Trivial** — `pip install duckdb`, no server at all | Yes but **heavy** — Coordinator + Historical + Broker + ZK/Kafka; 3+ containers | Yes as a coordinator; useful only with a real lake/catalog |
| **Hardware (single machine)** | 2-4 GB RAM comfortable for ~10^7-10^8 rows. **ASSUMPTION** | Runs on 1 GB; scales to whatever the laptop has | Wants 8-16 GB+; ~5.5 h to load a large benchmark set in one vendor-run benchmark. **VENDOR CLAIM (https://clickhouse.com/resources/engineering/best-columnar-databases)** | Needs a catalog + workers to be interesting |
| **Ease (4 students)** | **High** (SQL-compatible enough; great docs) | **Highest** — no service to run | **Low** — most moving parts of any option here | Medium |
| **Geo + TS fit** | Geo: good (`point`, geo functions; not full PostGIS) ; TS: **excellent** (`MergeTree`, TTL, rollups) | Geo: via `spatial` extension (real, PostGIS-like functions); TS: excellent on Parquet | TS: excellent; Geo: weak | Geo: depends on connector; TS: good |
| **Friction** | ClickHouse SQL dialect quirks; joins weaker than Postgres | Single-writer, single-node; no concurrent multi-user server story (except MotherDuck) | Kafka + ZK + 3 services to keep alive | Heavy for the payoff; needs a real catalog to shine |
| **Compare?** | ★ | ★ | ~ (do NOT run Druid on a laptop for a 4-person course project) | ~ |

**Critical, widely-cited nuance**: at **~10 GB scale, DuckDB ≈ ClickHouse**; ClickHouse wins only at **100 GB+/petabyte** scale. Reported by multiple independent comparisons, and even MotherDuck (DuckDB's own vendor) says ClickHouse wins on raw scan speed at PB scale while DuckDB wins "almost everywhere else". **VERIFIED (https://oneuptime.com/blog/post/2026-03-31-clickhouse-vs-duckdb-analytical-workloads/view, https://motherduck.com/learn/fastest-olap-databases-compared/)** → *This is a genuine, honest comparison insight for your report: "columnar engine choice matters less than expected at our scale; here is where the crossover begins."* That is a far better slide than a fabricated ClickHouse victory.

#### 4.1.4 Wide-column, time-series, document, search, graph

| | Apache Cassandra | TimescaleDB | MongoDB | Elasticsearch | Neo4j | PostGIS |
|---|---|---|---|---|---|---|
| **Best at** | Massive write throughput, multi-DC, no single point of failure; linear write scaling | PostgreSQL + hypertables/continuous aggregates; SQL time-series **without leaving Postgres** | Flexible document model; fast iteration; geospatial `2dsphere` indexes | Full-text search + log/event analytics + aggregations | Native property graph; Cypher traversal; GDS pathfinding/centrality | **Gold standard relational-spatial**: geometry/geography types, GiST/SP-GiST indexes, pgRouting |
| **Stream vs batch** | Both (write-optimised; reads need careful modelling) | Both (best-in-class: hypertables + compression) | Both (Change Streams) | Both (Logstash/Beats; near-real-time index refresh) | Batch/OLTP; streaming via Kafka connector (paid-ish tooling) | Batch primarily; streaming via CDC |
| **OSS/paid + free tier** | Apache-2.0 free; DataStax Astra paid | TimescaleDB OSS (Apache-2, generous TSL for advanced); Tiger Cloud paid. **VERIFIED (https://news.ycombinator.com/item?id=33230260)** | **SSPL** since Oct 2018 (not OSI). **Atlas M0 free tier = 512 MB.** **VERIFIED (https://www.mongodb.com/legal/licensing/community-edition, https://www.mongodb.com/pricing)** | Returned to **AGPLv3 as an option in 2024** alongside Elastic License/SSPL. **VERIFIED (https://www.elastic.co/pricing/faq/licensing)** | GPLv3 (Community) / commercial (Enterprise, GDS). **AuraDB Free: no credit card, no time limit** — limits reported inconsistently (older docs: 50k nodes/175k rels; FAQ/pricing: 200k nodes/400k rels). **VERIFIED-with-caveat (https://neo4j.com/free-graph-database/, https://neo4j.com/cloud/platform/aura-graph-database/faq/)** | **PostgreSQL licence (open) + GPL pgRouting**. Fully free. |
| **Docker/local** | Yes, but a *cluster* is needed for the point of using it (3+ nodes) | **Yes, trivially** — it is just a Postgres extension | Yes, single container | Yes but RAM-hungry (JVM, wants 2-4 GB min) | Yes, single container (Community); GDS plugin needed for algorithms | **Yes, trivially** |
| **Ease** | **Low-Medium** — CQL data modelling (query-first, denormalised) + cluster ops is the steepest learning curve on this row | **High** | **High** | Medium | Medium (Cypher is easy; GDS + tuning is not) | **High** if the team knows SQL |
| **Geo + TS fit** | Geo: weak/limited (no real spatial index) ; TS: strong writes, weak ad-hoc analytics | **Excellent TS**; Geo via PostGIS (same DB!) | Geo: good (`2dsphere`); TS: time-series collections exist but weaker analytics | Geo: `geo_point`/`geo_shape`; TS: good for logs | Geo: coordinates as properties only — **no spatial index**; routing is graph-native | **Excellent both** |
| **Friction** | Modelling mistakes are expensive; no joins; ops burden | Must stay within Postgres extensions; no distributed scale-out like Cassandra | Flexible schema → correctness discipline is on you; SSPL blocks some managed use | Licence history confuses corporate readers; heavy for small data | GDS/Enterprise features are paid; CSV/OSM import is fiddly | Not for write-huge ingest; vertical scaling only |
| **Compare?** | ★ (vs ClickHouse: write-heavy row-store vs read-heavy column-store) | ~ (great *supporting* tech, weak comparison) | ~ (good vs Elasticsearch for the serving layer) | ~ | ★ (vs PostGIS/pgRouting for routing) | ★ |

**Take on graph vs relational-spatial**: this is a *genuinely interesting* comparison because both genuinely solve routing, with different strengths. But be honest about the trap: **Neo4j has no spatial index** — for "nearby stops within 500 m" you want PostGIS; for "cheapest multimodal journey with transfer penalties and operators as first-class entities" you want the graph. A comparison that concludes *"use both for different parts"* is a legitimate, better answer than forcing a winner, **provided you measure something** (see §5-D).
### 4.2 Data processing

| | Apache Spark (batch) | Spark Structured Streaming | Apache Flink | Kafka Streams | Hadoop MapReduce | Apache Storm |
|---|---|---|---|---|---|---|
| **Best at** | Distributed batch ETL/ML over Parquet/lakehouse; the de-facto batch engine | Micro-batch streaming **on the same engine/API as batch** — unify batch + stream in one codebase | True per-event stream processing; champion of event time, watermarks, stateful processing, exactly-once | Library, not a cluster: stream processing *inside* your app, exactly-once on Kafka | The original distributed batch model; disk-based | Oldest low-latency stream engine; at-least-once, no state/event-time story |
| **Latency profile** | N/A (job) | **Micro-batch: ~100 ms - seconds** depending on trigger interval | **Per-event: true low-latency (~ms)**, and arguably stronger native event-time semantics | ms-seconds; no external cluster | Minutes-hours (disk shuffle) | sub-second |
| **Event time / watermarks** | Batch = processing time only | **Yes** — `withWatermark`, event-time windows, late-data handling. **VERIFIED (https://www.redpanda.com/guides/event-stream-processing-flink-vs-spark, https://aws.amazon.com/blogs/big-data/a-side-by-side-comparison-of-apache-spark-and-apache-flink-for-common-streaming-use-cases/)** | **Yes — and this is its home turf**; watermark + allowed-lateness + side outputs for late events. Same source. | Yes (KTable/windows, event time supported) | No | No (no event time) |
| **OSS/paid + free tier** | Apache-2.0, free. Databricks/Synapse/EMR/Dataproc are paid (Databricks has a free edition) | same | Apache-2.0, free. AWS Managed Flink, Confluent, Ververica paid | Apache-2.0 free; Confluent platform adds paid bits | Apache-2.0 (Hadoop 3.4), free, effectively legacy | Apache-2.0, free, effectively legacy |
| **Docker/local on a laptop** | **Yes** — local mode / `spark-submit` with 4-8 GB+ heap | **Yes** — same | **Yes** — JobManager + TaskManager, light-ish | **Yes** — it is just a JVM library | Yes (single-node pseudo-distributed) but pointlessly heavy | Yes but pointless |
| **Hardware** | 8-16 GB RAM recommended. **ASSUMPTION** | +extra for state/checkpoint store | 4-8 GB comfortable | trivial | 8 GB+ | 4 GB |
| **Ease (4 students)** | High (PySpark) | **Medium-High** — same API as batch is a huge win; fewer new concepts | **Medium** — steeper (state backends, savepoints, checkpointing, Flink SQL vs DataStream API duality) | High if the team writes JVM **or** uses a Python/other port — Kafka Streams is Java/Scala-first, which is a friction point for a Python team | Medium but obsolete skills | Low value |
| **Correctness features** | idempotent writes, ACID with Delta/Iceberg | Checkpointing, exactly-once to Delta/Iceberg/Kafka | Checkpointing + savepoints (savepoints are Flink's edge for planned upgrades) | exactly-once via Kafka transactions | none | at-least-once only |
| **Backpressure/late data** | microbatch naturally backpressures | microbatch amortises; lateness controlled by watermark | per-event backpressure; side output for late data | limited | N/A | weak |
| **Compare?** | ★ (batch vs stream for the same KPI) | **★ — the flagship comparison** | **★ — the flagship comparison** | ~ | – | – |

**Take on the flagship comparison**: **Spark Structured Streaming vs Flink** is the single most defensible pair on this list, because:
- Both are Apache projects, both are free, both support **event time and watermarks** (so the comparison is about *engineering trade-offs*, not about a feature gap that makes it a strawman).
- The trade-off is real and documented: Flink = lower latency, per-event, richer streaming semantics; Spark-SS = micro-batch, unified batch+stream codebase, easier for a team already writing PySpark, better throughput per unit of operational complexity for many workloads. **VERIFIED (https://www.confluent.io/compare/spark-streaming-vs-flink/, https://www.automq.com/blog/apache-flink-vs-spark-comprehensive-comparison)**
- GTFS-RT gives you genuine late/out-of-order data, so the *watermark/late-data* dimension is measurable, not hypothetical.

**Hadoop MapReduce and Storm**: include them in the report as *historical/contextual* technologies with a documented reason for rejection (MapReduce = disk-based batch, superseded by Spark for iterativity; Storm = trivially-limited event-time/state model, superseded by Flink). Rejecting them with evidence is itself good "technology content". Do not try to install Hadoop in the critical path.

**Kafka Streams**: on the menu, and worth a paragraph — but it is a *library*, so it is a different category from Spark-SS/Flink (no cluster, no separate runtime). If the team is Java-capable it could be a third processing point; realistically, mention and skip.

### 4.3 Supporting / platform layer

| | Apache Kafka | Debezium | Airflow | dbt | Grafana / Metabase / Superset | Streamlit / FastAPI |
|---|---|---|---|---|---|---|
| **Best at** | Durable, replayable, partitioned event log — the *shared substrate* that makes comparisons fair | CDC from Postgres/MySQL into Kafka (change capture without app changes) | Batch DAG orchestration, backfills, retries, scheduling | SQL transformations + tests + docs (the "T" in ELT) | BI dashboards over the serving layer | The application users actually touch |
| **OSS/paid** | Apache-2.0 (Kafka 4.x, KRaft-only, no ZooKeeper); Confluent Cloud trial gives **$400 for first 30 days**. **VERIFIED (https://www.confluent.io/get-started/)** | Apache-2.0 | Apache-2.0 | Apache-2.0 (core) / dbt Cloud paid | Grafana AGPL; Metabase/Superset open core | MIT / BSD |
| **Docker/local** | **Yes** — KRaft single broker is now simple (no ZK container). **VERIFIED (https://developer.confluent.io/confluent-tutorials/kafka-on-docker/)** | Yes | Yes (heavier: scheduler + webserver + a metadata DB) | Yes (`dbt-duckdb` allows zero-DB runs) | Yes | Trivially (Python) |
| **Ease** | High | Medium | Medium | Medium-High | High | High |
| **Do you need it?** | **Yes — non-negotiable**, it is the fairness backbone + replay source | Only if a business requirement needs CDC from an operational DB | Optional; cron/Make is enough for a semester project, Airflow adds credibility + backfill evidence | Optional but high value/low cost for correctness tests | **Yes — pick one** for "application data-exploitation effectiveness" evidence | **Yes** — the demo/product |

**Debezium note**: it is a genuinely nice "extra illustrative example" if a business requirement involves a *source operational database* (e.g., a mock ticket-booking OLTP DB whose inserts must reach the lakehouse). It is not needed for the core GTFS pipeline. Treat as optional bonus, not core.
### 4.4 Master scorecard for THIS project

Scores 1-5 (5 = best) for a 4-student, one-semester, Transportation project on student hardware. **ASSUMPTION-based**, derived from §4.1-4.3 evidence — treat as a starting ranking, not gospel.

| Technology | Role fit | Student ease | Free/2026 cost safety | Laptop-runnable | Geo+TS fit | Compare value | **Verdict** |
|---|---|---|---|---|---|---|---|
| **Apache Kafka** | 5 | 4 | 5 | 5 | N/A (transport) | 4 | **ADOPT — core substrate** |
| **Spark Structured Streaming** | 5 | 4 | 5 | 4 | 4 | 5 | **ADOPT — processing primary** |
| **Apache Flink** | 5 | 3 | 5 | 4 | 4 | 5 | **ADOPT — processing alternative** |
| **MinIO** | 5 | 5 | 5 | 5 | N/A | 3 | **ADOPT — storage substrate** |
| **Delta Lake** | 5 | 4 | 5 | 5 | 4 | 3 | **ADOPT — table format primary** |
| **Apache Iceberg** | 5 | 3 | 5 | 5 | 4 | 4 | MENTION / optional swap |
| **Apache Hudi** | 3 | 2 | 5 | 3 | 3 | 2 | **REJECT (concept load)** |
| **ClickHouse** | 5 | 4 | 5 | 5 | 4 | 5 | **ADOPT — storage alternative** |
| **DuckDB** | 4 | 5 | 5 | 5 | 4 | 4 | **ADOPT — baseline / dev tool** |
| **PostgreSQL + PostGIS** | 5 | 5 | 5 | 5 | 5 | 4 | **ADOPT — spatial reference** |
| **TimescaleDB** | 4 | 5 | 5 | 5 | 5 | 2 | Optional (TS support) |
| **Neo4j** | 3 | 3 | 3 (Aura limits) | 4 | 2 | 5 | **ADOPT-OPTIONAL — graph alternative** |
| **BigQuery** | 4 | 5 | 4 | N/A | 4 | 5 | **CONSIDER — managed comparison arm** |
| **Cassandra** | 4 | 2 | 5 | 3 (cluster) | 2 | 4 | Consider only if the team has an ops-minded member |
| **MongoDB** | 3 | 4 | 4 | 5 | 3 | 3 | Optional serving layer |
| **Elasticsearch** | 3 | 3 | 5 | 3 (RAM) | 3 | 3 | Optional serving layer |
| **Trino/Presto** | 3 | 2 | 5 | 4 | 3 | 3 | Optional lake query engine |
| **Apache Druid** | 2 | 1 | 5 | **1** | 3 | 3 | **REJECT for laptop** |
| **Apache Airflow** | 4 | 3 | 5 | 4 | N/A | 2 | Optional orchestrator |
| **dbt** | 3 | 4 | 5 | 5 | N/A | 2 | Optional (correctness tests) |
| **Debezium** | 3 | 3 | 5 | 5 | N/A | 3 | Optional bonus example |
| **Databricks Free Edition** | 4 | 4 | 4 | N/A | 4 | 3 | Optional managed alternative |
| **Redshift** | 3 | 3 | 3 | N/A | 2 | 4 | Optional (better: BigQuery) |
| **Synapse Analytics** | 3 | 2 | 3 | N/A | 2 | 2 | **REJECT (strategic retreat → Fabric)** |
| **Hive** | 2 | 2 | 5 | 2 | 2 | 2 | **REJECT (legacy; note as context)** |
| **Hadoop MapReduce** | 2 | 2 | 5 | 2 | 1 | 3 | **REJECT (legacy; use as contrast in report)** |
| **Apache Storm** | 1 | 2 | 5 | 4 | 1 | 2 | **REJECT (superseded)** |
| **Kafka Streams** | 3 | 3 | 5 | 5 | 2 | 3 | Mention only |
| **CouchBase / RavenDB / DynamoDB** | 2 | 3 | 3 | 3 | 2 | 2 | **REJECT (off-menu-fit, no advantage here)** |
| **Oracle data lakehouse** | 2 | 2 | 2 | 1 | 4 | 2 | **REJECT (cost/licensing)** |

**Reading of the scorecard**: the adopt-set is deliberately small — Kafka, Spark-SS, Flink, MinIO, Delta, ClickHouse, DuckDB, PostGIS. Everything else is either *context to be discussed and rejected with reasons* (Hadoop/Storm/Hive/Synapse/Druid) or an optional second axis. Note that **CouchBase, RavenDB, DynamoDB and Oracle** are on the instructor's menu but have no natural advantage for transportation data — the report should say so explicitly, in one line each, rather than ignore them.

---

## 5. Proposed comparison experiments

Each experiment below is a **same-problem, different-engine** comparison with a real engineering question, a measurable outcome, a fairness contract, and an expected insight. Pair each with 2-3 business requirements so C4/C8/C9 stay coupled.

### Experiment A — Stream semantics: Spark Structured Streaming (micro-batch) vs Flink (event-time)

**Engineering question**: *For GTFS-Realtime delay computation, how much end-to-end latency do we buy with a true event-time streaming engine, and what does that cost in operational complexity and late-data correctness?*

| | Primary (A1) | Alternative (A2) |
|---|---|---|
| Engine | Spark Structured Streaming, trigger = 10 s | Apache Flink, checkpointing 10 s |
| Input | Kafka topic `gtfs-rt.tripupdates` (replayed at controlled rate) | identical topic, identical offsets |
| Logic | Tumbling 1-min event-time window per (route, stop); computed delay = actual − scheduled from GTFS static join | identical logic, identical window |
| Sink | Delta Lake on MinIO | Delta Lake on MinIO |

**What is measured**
1. **Latency**: event-time → result-visible (event-time-completion) p50/p95/p99, plus ingestion→sink-visible latency.
2. **Throughput**: sustained events/s at a fixed latency SLO (find the knee; report max stable rate).
3. **Correctness**: (a) lag/error distribution vs the agency's own TripUpdate delay (when available); (b) **% of late events correctly windowed** for injected lateness of 0/30/120 s; (c) duplicate-handling (replayed duplicates must not double-count); (d) **conservation check**: events_in == events_out + late_dropped + dead-lettered.
4. **Operational cost**: containers, memory, restart-recovery time from checkpoint after kill -9, LOC/config complexity.

**Fairness contract**: same Kafka topic + same offsets; same output table schema; same window length; same watermark/allowed-lateness policy; same hardware (same laptop or same VM); same replay speed; same injected-lateness scenario set; both starting cold; ≥3 runs, report median + min/max.

**Expected insight (hypothesis, to be confirmed or falsified)**: Flink yields materially lower tail latency (p95/p99) and cleaner per-event late-data semantics (side outputs); Spark-SS is simpler, amortises throughput better, and reuses the batch code path — so **the honest conclusion is likely "Spark-SS unless you need sub-second tail latency"**, which is exactly the kind of trade-off statement the rubric rewards. Either result is a valid, publishable finding; do not pre-commit to a winner.

**Why this is >superficial**: it isolates one variable (execution model) with an identical business KPI, and it probes a documented difference. **VERIFIED (https://www.confluent.io/compare/spark-streaming-vs-flink/)**

---

### Experiment B — Storage engine for traffic time-series: Cassandra (write-optimised row/wide-column) vs ClickHouse (read-optimised columnar)

**Engineering question**: *For high-rate traffic/AVL sensor time-series, where is the write-throughput vs analytical-read crossover, and how much does columnar compression change storage cost?*

| | Primary (B1) | Alternative (B2) |
|---|---|---|
| Store | ClickHouse (`MergeTree`, partition by day, order by (sensor_id, ts)) | Apache Cassandra (partition key = (sensor_id, day), clustering = ts) |
| Data | Synthetic + real traffic counts / AVL pings: **10^7 rows minimum, scale to 10^8** | identical dataset |
| Loading | Kafka engine / `clickhouse-client` batch insert | Kafka→Cassandra via connector or driver batch writes |

**What is measured**
1. **Ingest**: rows/s sustained at ≥95% success, p99 write latency, degradation under concurrency (4 writers).
2. **Storage**: on-disk bytes for identical data (compression ratio) — this is where columnar usually wins by 3-10x. **ASSUMPTION**
3. **Read**: latency for a fixed 20-query suite — time-range aggregation, per-sensor percentiles, 5-min rollups, top-N congested corridors, geo-bucketed counts.
4. **Mixed workload**: reads/s while ingesting at a fixed rate (the realistic case).
5. **Correctness parity**: both stores must return identical results for the 20 queries (run in DuckDB as the reference for the 10 that are expressible there) → this is your "data correctness after data engineering" evidence.

**Fairness contract**: same rows, same schema semantics (fully denormalised in both — no join advantage), same hardware, same replication factor (1), same concurrency, same warm-up policy (declare and apply one to both), identical query set with query text published.

**Expected insight**: Cassandra wins raw write throughput and horizontal write scaling (at the cost of a cluster); ClickHouse wins analytical latency and storage footprint by a wide margin and is far easier to operate at small scale. **Cassandra's advantage only appears if you actually run 3 nodes** — if you run 1 node, say so and treat the result as a modelling exercise, not a Cassandra verdict. *(This honesty is itself a scoring point; a 1-node Cassandra benchmark presented as a fair Cassandra benchmark is a methodological hole a good grader will find.)*

---

### Experiment C — Lakehouse vs local columnar vs managed warehouse for trip records

**Engineering question**: *At 10^7-10^8 trip records, how do a self-hosted open lakehouse, an in-process columnar engine, and a managed serverless warehouse compare on latency, correctness guarantees (ACID/upsert/time-travel), and cost?*

Three arms (C3 is optional if budget-limited):

| | C1 — Lakehouse | C2 — Local columnar | C3 — Managed warehouse |
|---|---|---|---|
| Stack | Delta Lake on MinIO + DuckDB or Trino for SQL | DuckDB directly over Parquet on MinIO/local disk | BigQuery (Free sandbox) |
| Data | Same Parquet-derived trip record dataset, three layouts: raw, partitioned-by-date, Z-ORDER/clustered | same | same, loaded into a native table |
| Workload | 25 queries: aggregations, window functions, joins to GTFS, time-travel re-read of a previous version | same | same |

**What is measured**
1. **Query latency**: cold and warm, p50/p95 across the 25 queries (report both aggregate and per-query; a single total hides everything interesting).
2. **Ingest→queryable freshness**: seconds between a Kafka event landing and being queryable in each arm — this is where the lakehouse's small-file problem shows up, and where BigQuery's streaming insert shines/costs.
3. **Storage cost**: bytes on disk vs bytes billed (BigQuery bills logical/physical; note which).
4. **Money cost**: measured $ per full benchmark run (from billing dashboards) + extrapolated $/month at 10x. Compare against $0 for C1/C2 on owned hardware — but **do not equate $0 with free**: report operator-hours too.
5. **Correctness/ACID**: concurrent upsert + read behaviour, schema evolution test, time-travel read parity, and **parity of all 25 query results across arms** (golden results produced once, verified thrice).
6. **Small-file/compaction**: number of files and query latency before vs after `OPTIMIZE`/compaction — a classic, high-value insight.

**Fairness contract**: identical logical data and layout where the engine permits; same partitioning scheme declared and justified; same hardware class (for C1/C2) and explicitly note that C3 runs on different (vendor) hardware — meaning **C3 can only be compared on latency-vs-cost, not on hardware-normalised speed**. State this limitation in the report; it is the difference between a benchmark and a marketing slide.

**Expected insight**: at 10^7-10^8 rows, DuckDB-over-Parquet is likely competitive-to-better than both, at zero ops cost; the lakehouse's value is *correctness + governance + multi-engine*, not raw speed; BigQuery's value is zero-ops + true scale, paid for in $/TB-scanned and egress. **VERIFIED for the DuckDB≈ClickHouse component at ~10 GB (https://oneuptime.com/blog/post/2026-03-31-clickhouse-vs-duckdb-analytical-workloads/view)**; the DuckDB vs BigQuery-at-scale comparison is **ASSUMPTION** and must be measured. Note honestly that BigQuery will likely win on throughput at large scale on a cold query — say so and explain *why the answer is still "both, for different phases"*.

---

### Experiment D — Multimodal routing: PostGIS/pgRouting (relational-spatial) vs Neo4j (graph)

**Engineering question**: *For multimodal journey planning (bus + metro + walking, with transfers), does a spatial-relational engine or a property-graph engine deliver better modelling expressiveness and query latency, and where does each break down?*

| | Primary (D1) | Alternative (D2) |
|---|---|---|
| Engine | PostgreSQL 16 + PostGIS + pgRouting (`pgr_dijkstra`, `pgr_ksp`) | Neo4j Community + GDS (Dijkstra, A*, allShortestPaths) |
| Graph | Road/transit network as nodes/edges tables with geometry; cost = travel time | Same network as `(:Stop)-[:RIDE {time}]->(:Stop)`, `(:Stop)-[:WALK {time, distance}]->(:Stop)`, `(:Line)`, `(:Operator)` |
| Data | Same city OSM extract + same GTFS; same origin-destination sample (e.g., 500 O-D pairs) | identical |

**What is measured**
1. **Routing latency**: p50/p95 for 500 O-D pairs, per engine, warm and cold.
2. **Correctness**: (a) both engines' k-shortest-path results compared on total travel time (allow ±ε for tie-breaking on equal-cost paths); (b) vs a reference implementation (e.g., OpenTripPlanner or a hand-checked baseline on 10 O-D pairs) — **this is your strongest correctness evidence in the whole project**.
3. **Expressiveness (qualitative, scored)**: how many LOC / schema concepts to express (i) transfer penalty, (ii) operator preference, (iii) "avoid this stop", (iv) service-hours/time-dependent edges, (v) isochrones (X minutes reach).
4. **Update cost**: time to insert/modify 100 edges, and time to rebuild indexes — transit networks change.
5. **Spatial-query capability**: "stops within 500 m of a point" — measure; **expect PostGIS to win decisively because Neo4j has no native spatial index**. **ASSUMPTION / widely-observed (https://gis.stackexchange.com/questions/13943/help-choosing-a-suitable-routing-engine)**

**Fairness contract**: same network, same O-D set, same cost function (travel time only), same hardware, same query semantics, pre-warmed caches for both, single-threaded where the engine allows (or declare multi-threading for both).

**Expected insight**: graph = better model for multimodal/transfer problems and far more legible queries; PostGIS = better spatial indexing, better integration with the rest of your relational/lakehouse stack, and strong enough routing for simple shortest paths. **A conclusion of "graph for topology, spatial DB for geometry" is a legitimate and superior engineering answer** — provided you measured both. Also honestly note that production transit routing at scale uses custom engines (RAPTOR/CSA), which neither arm is — this shows domain literacy.

---

### Experiment E (stretch) — Batch vs streaming for the same KPI: Lambda vs Kappa

**Engineering question**: *For "on-time performance by route", what does real-time incremental computation cost in correctness and freshness versus a nightly batch recomputation — and do the two ever disagree?*

| | Primary (E1) | Alternative (E2) |
|---|---|---|
| Path | Nightly Spark batch over the full day's data (Delta Lake) | Flink/Spark-SS continuous incremental OTP computation |
| KPI | % trips on time (≤5 min late) by route/hour | identical definition, identical GTFS static join |

**Measured**: (1) **freshness** — age of the KPI at any point in the day (batch = up to 24 h stale; stream = seconds); (2) **compute cost** — total CPU-minutes/energy for batch vs stream over a full simulation day; (3) **correctness divergence** — after the day ends, do the two agree exactly? If not, **attribute every discrepancy** (late events, dedup, boundary/watermark effects, corrections after the fact). Discrepancy attribution is the single richest source of "data correctness" discussion you can get in this course.

**Expected insight**: Lambda-style batch is cheap, simple, and exact; streaming buys freshness and pays in late-data correctness handling. Divergence analysis produces concrete, citable numbers — far more impressive than a wall-clock speedup.

---

### Comparison-pair summary

| # | Pair | Axis | Question | Measured | Insight |
|---|---|---|---|---|---|
| **A** | Spark-SS vs Flink | Processing | Latency cost of a true event-time engine | p50/p95/p99 latency, throughput knee, late-event correctness, recovery | Micro-batch vs per-event trade-off |
| **B** | ClickHouse vs Cassandra | Storage engine | Write-rate vs analytical-read crossover | ingest r/s, read latency, compression, mixed load | Row/write-optimised vs column/read-optimised |
| **C** | Delta-on-MinIO vs DuckDB-vs-BigQuery | Storage architecture | Lakehouse vs local columnar vs managed warehouse | query latency, freshness, $/run, ACID parity | Where the lakehouse actually pays off |
| **D** | PostGIS/pgRouting vs Neo4j | Modelling paradigm | Relational-spatial vs graph for routing | routing latency, k-path correctness, LOC/expressiveness, spatial queries | Graph topology vs spatial index |
| **E** | Batch vs stream (same KPI) | Architecture | Lambda vs Kappa cost of freshness | freshness, compute, exact divergence | Cost of freshness + correctness attribution |

**Recommendation**: do **A + C** as the mandatory pair-set (they cover processing and storage, which the rubric names explicitly), add **B or D** if the team has bandwidth, and use **E** as the "extra alternative" that earns the bonus. Two axes executed rigorously > four axes executed superficially.
---

## 6. Benchmarking methodology

The rubric awards 1/10 for evaluation but requires **">85% of evaluation criteria clearly defined"**. That phrase means: a reader must be able to take your criteria list and know exactly *what* is measured, *with what instrument*, *at what threshold*, and *whether it passed*. Vague criteria ("performance was good") score zero.

### 6.1 Define metrics operationally (write these as a table in the report)

| Dimension | Metric | Instrument | Unit | Threshold / pass rule |
|---|---|---|---|---|
| Throughput | Sustained ingest rate at p99 latency ≤ SLO | Producer-side counter + consumer lag (Kafka `consumer_lag`) | events/s | Report the knee; no pass/fail, report the curve |
| Throughput | Analytical query throughput | Query runner, N iterations after warm-up | queries/s | Report per-query, not just mean |
| Latency | Event-time → result-visible | Embedded event timestamp diff (watermark completion time − event time) | ms | p50, p95, p99 (never only mean) |
| Latency | Query latency | Query runner, cold + warm separated | ms | p50/p95 per query, cold and warm |
| Latency | Recovery time | `kill -9` the worker; time until processing resumes from checkpoint | s | Declared SLO |
| Correctness | Golden-result parity | Compare against a reference implementation (DuckDB / hand-computed on a sample) | % matching rows / absolute error | Require exact match or state tolerance |
| Correctness | Late-event handling | Injected lateness scenarios (0 / 30 / 120 s) | % correctly windowed | ≥ declared target per scenario |
| Correctness | Conservation | events_in == events_out + late_dropped + dead_letter | count | Must be exact; any drift is a bug to explain |
| Correctness | Duplicate idempotency | Replay with duplicates | final row count vs expected | Exact |
| Cost | Compute | wall-clock × vCPU × $/vCPU-hour, or cloud billing dashboard | $ per run | Report both $ and $/month at 10x extrapolation |
| Cost | Storage | bytes on disk / bytes billed | GB | Report compression ratio |
| Cost | Operator effort | honest engineer-hours per arm | hours | Report; do not hide it behind "$0 cloud" |
| Effectiveness | BR coverage | count of business requirements demonstrable in the app | # of 8+ | Coverage >85% |
| Effectiveness | Time-to-insight | stopwatch on a defined analyst task per arm | s | Report |

### 6.2 Rules that make comparisons fair (this is the section graders attack)

1. **Identical data.** Same dataset, same row counts, same distribution, same file layout where the engine permits. Publish a checksum/`row_count` per arm.
2. **Identical logic.** Same window length, same watermark policy, same cost function, same query semantics. If an engine cannot express something natively, say so — that *is* a finding.
3. **Identical hardware.** Same laptop or same VM size for all self-hosted arms. For managed arms, state clearly that hardware is not comparable and restrict claims to latency-vs-cost.
4. **Symmetric tuning.** Tune both arms or tune neither. Asymmetric tuning (hand-optimised Spark vs default Flink) invalidates the comparison and is the most common serious flaw in student benchmarks.
5. **Warm-up disclosed.** Declare and apply the same number of warm-up iterations to all arms.
6. **Repeat and report spread.** ≥3 runs; report median with min/max. A single run is an anecdote.
7. **Isolate variables.** Change one thing per experiment. If you change both engine and hardware, you measured nothing.
8. **Cold vs warm separated.** Never mix them in one average.
9. **Declare what you did not test.** Missing scale, missing concurrency, missing failure injection — list them (§8).
10. **Never cite a vendor benchmark as your result.** You may cite it as *prior art* and then compare your own numbers to it, clearly labelled.

### 6.3 Correctness strategy (the axis most student projects under-serve)

- **Golden dataset first**: build a small (~10k row) dataset where the correct answer is computed by an independent method (SQL in DuckDB, or hand-checked) *before* any engine is benchmarked. Every engine is then graded against it. This converts correctness from a vibe into a number.
- **Property/invariant tests**: conservation of events; monotonicity of cumulative counts; "no result row may reference a trip_id absent from GTFS static"; "all coordinates within the bounding box"; "no timestamp before service start". These catch the bugs that parity tests miss.
- **Re-processing determinism**: re-run the same input; results must be byte-identical. Then *deliberately* re-process a corrected late arrival and demonstrate (via time travel in Delta/Iceberg) that the corrected result is reproducible and auditable. This is a strong, distinctive use of the lakehouse that most teams never demonstrate.
- **Cross-engine parity** as the comparison-grade correctness metric: all 25 queries must return identical results across arms, or you must explain each difference.

### 6.4 Reproducibility

- **One command up**: `docker compose up -d` for the whole stack; pinned image tags (`clickhouse/clickhouse-server:24.x`, `apache/kafka:3.x`/`4.x`, `minio/minio:RELEASE.x`) — never `latest`, because a silent image update destroys reproducibility.
- **Seeded synthetic generator**: one script, one seed → identical data every run, scale parameterised (`--rows 10_000_000`).
- **Version manifest**: commit OS, Docker version, image digests, Python/Java versions, hardware spec (CPU model, RAM, disk type), and a `docker compose config` dump.
- **Raw results committed**: CSV per run + the plotting script. Charts must be regenerable from committed CSVs.
- **Environment note in the report**: state that results are single-machine and not comparable to a distributed cluster. Pre-empt the objection.
- **Document the replay harness**: how you paced Kafka replay (rate, backpressure, lateness injection) is the single most important reproducibility detail for Experiments A and E.

### 6.5 Report structure for the evaluation chapter

Per experiment: **(1) Question → (2) Hypothesis → (3) Setup (diagram + versions + data) → (4) Metrics table → (5) Results (table + chart) → (6) Fairness notes & threats to validity → (7) Interpretation → (8) Decision.** Then a single cross-experiment **decision matrix** mapping each business requirement to the chosen technology with the evidence that justifies it. That mapping is what turns "we benchmarked things" into "we evaluated technologies for *this application*", which is what the rubric actually asks for.

---

## 7. Infrastructure reality check

### 7.1 Can a laptop run this? (per stack)

| Stack | Containers | Realistic RAM | Verdict on 16 GB laptop | Verdict on 32 GB laptop |
|---|---|---|---|---|
| Kafka (KRaft) only | 1 | ~1 GB | Fine | Fine |
| Kafka + MinIO + Postgres/PostGIS | 3 | ~3 GB | Fine | Fine |
| + ClickHouse | 4 | ~5 GB | OK if nothing else runs | Fine |
| + Spark (local 4 GB heap) | 5 | ~9-11 GB | **Tight but workable** — close Chrome/IDE | Fine |
| + Flink (JM+TM) | 6 | ~11-13 GB | **Will swap/thrash** | OK |
| + Neo4j | 7 | +1.5-3 GB | **No.** Split into separate compose profiles | Marginal |
| All of the above at once | 8+ | 16-20 GB+ | **No** | Borderline |
| Druid (Coord+Hist+Broker+ZK) | 4-5 just for Druid | 8-16 GB | **No** | Marginal, and not worth it |

**Practical rule**: define **two or three Docker Compose profiles** (e.g. `--profile streaming` with Kafka+Spark+MinIO+Delta; `--profile graph` with Neo4j+PostGIS) and never run both profiles simultaneously. Run experiments **sequentially**, not concurrently — a sequential benchmark is also a fairer benchmark, because resource contention is a confounding variable.

**Disk**: Spark + Delta + Parquet at 10^8 rows wants **50-150 GB free**. Cheap NVMe required; a full HDD will make every benchmark I/O-bound and your latency numbers meaningless. **ASSUMPTION** — verify free space before starting.

**CPU**: Spark/Flink on a 4-8 vCPU machine works but results are CPU-bound and noisy. Pin thread counts explicitly (e.g. `spark.master=local[4]`) so runs are comparable, and report the setting.

**WSL2 note (critical for Windows users, likely the whole team)**: Docker on Windows runs through WSL2, which needs memory limits configured in `.wslconfig`. Without it, WSL will consume RAM and the host will thrash. Set `memory=` and `processors=` in `.wslconfig` so the numbers are stable and reproducible. **ASSUMPTION (well-established practice)**. Also: keep experiments on the Linux filesystem inside WSL, not on `/mnt/c`, or I/O will be several times slower and non-representative.

### 7.2 Cloud options and the honest cost picture

| Option | What you get | Cost risk | Student fit |
|---|---|---|---|
| **Local Docker only** | Full stack, $0 | Disk/RAM only | **★ Recommended default** |
| **One cloud VM** (4 vCPU / 16 GB) | Real server, real networking, always-on | ~$0.13-0.20/vCPU-hr class → **~$100-150/month if left 24/7**. **ASSUMPTION** | Good if time-boxed + auto-stop; risky if forgotten |
| **Google Cloud** | $300/90-day credit + always-free tier (BigQuery 1 TiB/mo queries, 10 GiB storage). **VERIFIED (https://cloud.google.com/free)** | Credit expiry mid-project; BigQuery overage beyond 1 TiB | **★ Best managed arm** |
| **BigQuery sandbox** | Free, **no credit card**, 1 TiB/mo queries. **VERIFIED (https://cloud.google.com/free)** | Querying a wide table with `SELECT *` can burn 1 TiB in minutes | **★ Safest way to add a managed arm** |
| **AWS** | $100 signup credit + up to $100 earned = $200. **VERIFIED (https://aws.amazon.com/free/)** | Redshift RPU-hours, MSK hourly, NAT gateway hourly, egress — all silent drains | Use only with budget alerts + teardown checklist |
| **Azure for Students** | $100, no credit card, academic email. **VERIFIED (https://learn.microsoft.com/en-us/answers/questions/5837170/)** | Synapse DWU-hours; Fabric capacity is expensive | OK for storage/VM; avoid Synapse |
| **Databricks Free Edition** | Free, no cloud account needed; **replaced Community Edition, retired end of 2025**. **VERIFIED (https://www.databricks.com/learn/free-edition, https://learn.microsoft.com/en-us/azure/databricks/getting-started/free-edition)** | Quota/feature limits; not for heavy benchmarking | Good for a Spark-vs-Flink narrative demo, weak as a rigorous benchmark host |
| **Neo4j AuraDB Free** | Free, no credit card, no time limit; node/relationship cap (50k/175k or 200k/400k depending on source). **VERIFIED-with-caveat (https://neo4j.com/free-graph-database/)** | Capping out mid-demo; 200k nodes is fine for a city-scale transit graph but tight for full OSM | Good for the D2 arm if the extract is trimmed |
| **Confluent Cloud** | Trial: **$400 for first 30 days**. **VERIFIED (https://www.confluent.io/get-started/)** | **Expires in 30 days** — do not build the demo on it | Demo/backup only |
| **MongoDB Atlas M0** | Free 512 MB. **VERIFIED (https://www.mongodb.com/pricing)** | 512 MB is small | Serving-layer experiments only |

**Budget playbook for 4 students**: (1) build and benchmark everything locally; (2) use **BigQuery sandbox** for the single managed comparison arm (no card, hard budget ceiling); (3) if you need a VM, use one, with a **teardown checklist** and a hard stop date; (4) set billing alerts on day one; (5) never demo from a trial that expires before the presentation.

### 7.3 Team-of-4 operating model (how to actually finish)

| Member | Ownership |
|---|---|
| 1 | Ingest + Kafka + data generator/replay harness (the fairness backbone — own it early) |
| 2 | Processing axis A (Spark-SS) + Delta/MinIO lakehouse |
| 3 | Processing/storage axis B (Flink, ClickHouse/Cassandra/BigQuery arm) + benchmark harness |
| 4 | Serving layer + application + PostGIS/Neo4j + dbt correctness tests |

All four: business requirements, report, slides, video. **The benchmark harness must be shared code, not per-person scripts**, or the comparison will not be fair. Freeze the dataset and query set at ~week 6, then benchmark.

---

## 8. Risks, anti-patterns, and unresolved questions

### 8.1 Top risks, ranked by probability × damage

| Risk | Impact | Mitigation |
|---|---|---|
| **Scope explosion** — 8 technologies, none demonstrated | High (loses most of the 8/10 Application Implementation) | Lock 2 comparison axes; everything else is a landscape-table row |
| **Unfair benchmark** (different data/hardware/tuning) | High (destroys the 1/10 Evaluation and the bonus) | Publish the fairness contract (§6.2) before running anything |
| **Cloud bill** (forgotten VM, BigQuery scan, Redshift RPU) | High | Budget alerts, teardown checklist, demo locally, prefer sandbox tiers |
| **Laptop limit** — running Spark+Flink+Neo4j+ClickHouse simultaneously | Medium-High | Compose profiles, sequential runs, 32 GB preferred, pin thread counts |
| **Cassandra on 1 node presented as a fair Cassandra result** | Medium | Either run 3 nodes or explicitly scope the claim |
| **Free-tier expiry before the demo** | Medium | Trial services (Confluent 30 days, GCP 90 days) must not be in the demo path |
| **DuckDB-vs-BigQuery scale mismatch** (can't load PB in a semester) | Medium | Scope the claim to the rows you actually tested; extrapolate transparently |
| **Neo4j free-tier cap mid-demo** | Medium | Trim the OSM extract; pre-load and snapshot before demo day |
| **Windows/WSL2 I/O and RAM surprises** | Medium | `.wslconfig` limits, data on the Linux filesystem, not `/mnt/c` |
| **Time-travel/ACID claims with no failure injection** | Low-Medium | Do one deliberate failure + re-process demo; it is cheap and high-scoring |
| **Legacy tech (Hadoop/Storm/Hive) consumed too much time** | Low-Medium | Discuss-and-reject in the report; do not install in the critical path |

### 8.2 Anti-patterns to avoid explicitly

1. **The technology zoo** — breadth without depth. The rubric's "Technology Content 4/10" rewards *thorough* treatment for *your* application, not a survey.
2. **Strawman alternatives** — comparing your tuned primary against an untuned default alternative. Graders who know the tech will notice.
3. **Managed vs local without cost normalisation** — BigQuery is not "faster than ClickHouse" on hardware it doesn't share.
4. **Mean-only latency** — always p50/p95/p99.
5. **Single-run benchmarks** — with no spread reported.
6. **`latest` Docker tags** — destroys reproducibility.
7. **Calling 10^6 rows "Big Data"** — say "medium-scale, architecture designed to scale", and prove scaling behaviour with synthetic volume.
8. **Ignoring the exploitation axis** — the app must *use* the data engineering results to answer the business requirements, per BR, with a demonstrated result (that is literally how the 8/10 Application Implementation score is computed).
9. **Citing vendor benchmarks as your own** — cite them as prior art only.

### 8.3 Unresolved questions (need a decision, not more research)

1. **Which transit agency's GTFS/GTFS-RT feeds?** Vietnam-local feeds would be most domain-authentic but availability/coverage is unverified; international feeds (e.g. large European/North American agencies) have richer GTFS-RT and open historical data. **UNVERIFIED — must be checked in `03-data-sources`.**
2. **Is real historical traffic-volume data obtainable and licensable** for the scale-up in Experiment B, or is synthetic generation with realistic distributions the only option?
3. **Language for the processing arms**: PySpark for both, or Scala/Java for Flink? PyFlink is workable but less documented; this choice materially affects Experiment A's fairness (a poorly-expressed PyFlink job is a strawman).
4. **Which business requirements** map to which comparison arm? (Needed to satisfy C4 and C8; belongs in the BR phase.)
5. **Is the team's hardware 16 GB or 32 GB?** Determines whether Experiments A and B can run on the same machine.
6. **Does the team want the graph arm (D) at all?** Highest insight-per-novelty, but it is a third axis and Neo4j free-tier caps + OSM import are real time sinks.
7. **Does the rubric's "8.5-10" technology band require anything beyond 3-4 illustrative examples?** Current reading: no — ">3 illustrative examples" plus thorough treatment. Confirm with the instructor.

---

## 9. References & verification log

All URLs accessed **2026-09-23**.

### Official docs & pricing (highest weight)
- GTFS Realtime Reference — https://gtfs.org/documentation/realtime/reference/
- Google Cloud free tier / BigQuery always-free — https://cloud.google.com/free
- AWS Free Tier ($100 + up to $100) — https://aws.amazon.com/free/
- Amazon Redshift free trial (2 months) — https://aws.amazon.com/redshift/free-trial/
- Azure SQL free offer (100k vCore-s/mo, 32 GB) — https://learn.microsoft.com/en-us/azure/azure-sql/database/free-offer
- Azure for Students ($100, no card) — https://learn.microsoft.com/en-us/answers/questions/5837170/question-about-azure-for-students
- Databricks Free Edition (replaces Community Edition) — https://www.databricks.com/learn/free-edition
- Databricks Free Edition (Azure docs) — https://learn.microsoft.com/en-us/azure/databricks/getting-started/free-edition
- Neo4j free graph database — https://neo4j.com/free-graph-database/
- Neo4j AuraDB FAQ (200k nodes / 400k rels) — https://neo4j.com/cloud/platform/aura-graph-database/faq/
- Neo4j pricing — https://neo4j.com/pricing/
- MongoDB licensing (SSPL) — https://www.mongodb.com/legal/licensing/community-edition
- MongoDB pricing (Atlas M0 = 512 MB) — https://www.mongodb.com/pricing
- Elastic licensing FAQ (AGPLv3 option) — https://www.elastic.co/pricing/faq/licensing
- Confluent Cloud get started ($400 / 30 days) — https://www.confluent.io/get-started/
- Confluent Cloud pricing — https://www.confluent.io/pricing/
- Kafka on Docker (official tutorial) — https://developer.confluent.io/confluent-tutorials/kafka-on-docker/
- Flink standalone on Docker (official) — https://nightlies.apache.org/flink/flink-docs-stable/docs/deployment/resource-providers/standalone/docker/
- Azure Synapse Data Explorer → Fabric migration (official) — https://learn.microsoft.com/en-us/fabric/real-time-intelligence/migrate-synapse-data-explorer
- AWS: side-by-side Spark vs Flink for streaming (official, technical) — https://aws.amazon.com/blogs/big-data/a-side-by-side-comparison-of-apache-spark-and-apache-flink-for-common-streaming-use-cases/

### Independent / technical analyses
- Redpanda: Flink vs Spark (event-time/watermark support in Spark) — https://www.redpanda.com/guides/event-stream-processing-flink-vs-spark
- Codecentric: event-time in Spark and Flink — https://www.codecentric.de/en/knowledge-hub/blog/event-time-processing-in-apache-spark-apache-flink
- Dremio: Iceberg vs Hudi vs Delta — https://www.dremio.com/blog/comparison-of-data-lake-table-formats-apache-iceberg-apache-hudi-and-delta-lake/
- Onehouse: Hudi vs Delta vs Iceberg feature comparison — https://www.onehouse.ai/blog/apache-hudi-vs-delta-lake-vs-apache-iceberg-lakehouse-feature-comparison
- Oneuptime: ClickHouse vs DuckDB (TPC-H SF10 comparable; SF100 divergence) — https://oneuptime.com/blog/post/2026-03-31-clickhouse-vs-duckdb-analytical-workloads/view
- MotherDuck: fastest OLAP databases compared (concedes ClickHouse at PB scale) — https://motherduck.com/learn/fastest-olap-databases-compared/
- StarTree: Pinot vs Trino vs ClickHouse on Iceberg (vendor) — https://startree.ai/resources/iceberg-query-benchmark-vs-trino-vs-clickhouse/
- Tinybird: ClickHouse vs Druid architectures — https://www.tinybird.co/blog/clickhouse-vs-druid
- GIS StackExchange: choosing a routing engine (pgRouting vs Neo4j) — https://gis.stackexchange.com/questions/13943/help-choosing-a-suitable-routing-engine
- StackShare: Neo4j vs pgRouting — https://stackshare.io/stackups/neo4j-vs-pgrouting
- Tech Insider: Redshift vs Snowflake vs BigQuery 2026 pricing — https://tech-insider.org/redshift-vs-snowflake-vs-bigquery-2026/
- Solv Systems / Avantiico on Synapse vs Fabric (no formal EOL, de-facto successor) — https://solv-systems.com/resources/fabric-vs-azure-synapse-2026 , https://avantiico.com/azure-synapse-vs-fabric-comparison-difference/
- Modern Hadoop/Hive/Kafka/Flink 2026 ecosystem deep dive — https://labhub.hopto.org/blog/culture/2026-05-16-modern-hadoop-big-data-2026-hadoop-3-4-spark-4-hive-4-kafka-4-flink-2-iceberg-trino-deep-dive
- Databricks Community Edition retirement PSA — https://www.reddit.com/r/databricks/comments/1pn7uwd/psa_community_edition_retires_at_the_end_of_2025/

### Vendor claims flagged as such (use as prior art, never as your result)
- ClickHouse: "Best columnar databases in 2026" (Druid load time 19,620 s; ClickHouse 148 ms median on ClickBench) — https://clickhouse.com/resources/engineering/best-columnar-databases
- ClickHouse: fastest OLAP databases 2026 — https://clickhouse.com/resources/engineering/fastest-olap-databases
- Confluent: Spark Streaming vs Flink comparison page — https://www.confluent.io/compare/spark-streaming-vs-flink/
- Confluent: Cloud vs MSK ("cuts TCO 40-70%") — https://www.confluent.io/compare/confluent-cloud-vs-amazon-msk/
- Onehouse: Spark-SS vs Flink vs Kafka Streams — https://www.onehouse.ai/blog/apache-spark-structured-streaming-vs-apache-flink-vs-apache-kafka-streams-comparing-stream-processing-engines

### Claim-status summary
- **VERIFIED**: Databricks CE retirement → Free Edition; Neo4j Aura Free exists (limits contested across sources); GCP $300 + BigQuery always-free/sandbox; AWS $100+$100; Redshift not in Free Tier but 2-month trial; Azure for Students $100; Azure SQL free offer; Synapse not formally EOL but Fabric is the successor and a migration banner exists; Spark-SS supports event time/watermarks; Flink = per-event low latency; ClickHouse/Apache-2.0 and DuckDB competitive at ~10 GB; MongoDB SSPL + Atlas M0 512 MB; Elasticsearch AGPLv3 option restored; Confluent trial $400/30 days; Kafka KRaft Docker (no ZooKeeper).
- **VENDOR CLAIM**: all "X is N× faster" numbers (ClickHouse, StarTree, Confluent, Onehouse).
- **ASSUMPTION**: RAM/disk footprints, laptop verdicts, TPC-H-scale crossover behaviour beyond cited sources, team operating model, cost-per-month estimates for VMs.
- **UNVERIFIED**: Cassandra 5.0 specifics, Oracle Always-Free data-lakehouse details, Vietnamese transit GTFS-RT feed availability and licensing, Synapse free-trial terms for student accounts.

---

*End of report. Next step: use §5 to select 2 comparison axes, then hand to `02-candidates` for scoring against the 8+ business requirements.*
