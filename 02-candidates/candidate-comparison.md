# Candidate Project Directions — Comparison & Ranking

**Course:** CO5173 Data Engineering · **Domain:** Transportation · **Team:** 4 students, 1 semester
**Date:** 2026-09-23
**Inputs:** `01-research/domain-problems-and-stakeholders.md`, `01-research/data-engineering-technology-landscape.md`, `03-data-sources/*.md`, `00-requirements/instructor-project-requirements.md`

> Purpose: reduce the transportation opportunity space to a defensible leading direction, with explicit
> criteria, transparent scores, and the decision points that require team/owner input.

---

## 1. Selection criteria (derived from the instructor's PROJECT rubric)

Weights are justified by the Project assessment scheme (Technology Content 4/10, Application Content 4/10,
Application Implementation 8/10 driven per-demonstrated-BR, Evaluation 1/10, plus the bonus clause).

| # | Criterion | Why it is weighted this way | Weight |
|---|---|---|---|
| C1 | **Data availability & licensing** | Hard gate: no data ⇒ no project. Verified open sources only. | 3 |
| C2 | **Data-engineering depth** (management **and** processing) | The course *is* data management + processing; both are mandatory. | 3 |
| C3 | **BR breadth & demonstrability** (≥8, each app-demonstrable) | Directly drives Application Content (4/10) and Implementation (8/10). | 3 |
| C4 | **Alternative solution + benchmarking potential** | Explicitly required ("at least one alternative"); bonus for more. | 3 |
| C5 | **Big-Data / streaming fit** | Instructor stresses benchmarking "especially in the Big Data context"; streaming processing is on the tech menu. | 2 |
| C6 | **Multi-source integration** | Integration is where data engineering earns its keep (not a CRUD app). | 2 |
| C7 | **User-group / stakeholder breadth** | Bonus clause explicitly rewards "more interesting BRs with more user groups". | 1 |
| C8 | **4-student feasibility & infrastructure** | Must finish in one semester on student hardware. | 3 |
| C9 | **Risk & reproducibility** | Findings must be reproducible for evaluation. | 2 |

Total weight = 22. Scores 1–5. Weighted score = Σ(score × weight) / 5 × 22 × 5 → reported as /110.

---

## 2. Ranked matrix

| Candidate (primary direction) | C1 Data | C2 DE depth | C3 BR breadth | C4 Alt/bench | C5 Stream | C6 Multi-src | C7 User groups | C8 Feasible | C9 Risk | **Weighted /110** |
|---|---|---|---|---|---|---|---|---|---|---|
| **D1 — Urban transit reliability & service-quality intelligence** | 5 | 5 | 5 | 5 | 5 | 4 | 5 | 4 | 4 | **103 (1st)** |
| **D4 — Maritime port congestion & vessel dwell (AIS)** | 4 | 5 | 5 | 4 | 5 | 5 | 5 | 3 | 3 | **94 (2nd=)** |
| **G1 — Transit feed data-quality observatory (Mobility Database corpus)** | 5 | 5 | 4 | 4 | 4 | 5 | 4 | 4 | 3 | **94 (2nd=)** |
| **D3 — Aviation network delay propagation** | 5 | 5 | 4 | 4 | 3 | 5 | 5 | 4 | 3 | **93 (4th)** |
| **D5 — Shared-mobility availability & rebalancing** | 4 | 4 | 4 | 4 | 4 | 4 | 4 | 5 | 4 | **91** |
| **D6 — Road-safety risk & severity mapping** | 5 | 4 | 4 | 3 | 2 | 5 | 5 | 5 | 4 | **90** |
| **D2 — Multimodal accessibility & equity** | 5 | 4 | 4 | 4 | 2 | 5 | 4 | 4 | 4 | **89** |
| **V0 — Vietnam-only batch (Hanoi GTFS + OSM + TomTom)** | 2 | 3 | 3 | 3 | 1 | 4 | 3 | 5 | 4 | **69 (last)** |

Sensitivity note: the ordering between D1/D4/G1/D3 is close (93–103). The decisive differences are **streaming
fit**, **data obtention risk**, and **benchmarking depth**, not raw scale. V0 is dominated on exactly the axes
the rubric rewards, and is retained only as a *case-study layer*, not a primary direction.

---

## 3. Per-candidate critique (strengths / weaknesses / risks)

### D1 — Urban transit reliability & service-quality intelligence — **RECOMMENDED PRIMARY**
- **What:** Reconstruct delivered vs scheduled service (on-time performance, headway regularity, bus bunching, missing trips, delay attribution) from GTFS static + GTFS-Realtime for one or more agencies.
- **Strengths:** data is open, licensed, genuinely streaming (protobuf, real late/out-of-order events); five distinct user groups each with a concrete decision; 8+ demonstrable BRs fall out naturally; alternative axes are honest and sharp (Spark-SS vs Flink; lakehouse vs columnar vs managed warehouse); external methodology benchmarks exist (MBTA, TRB/SMARTER) so evaluation criteria are anchored, not invented.
- **Weaknesses:** metrics are well-understood (less novel than AIS); needs careful feed selection.
- **Risks:** agency feed stability; timezone/service-day correctness; realtime feed gaps. Mitigation: pick 2–3 stable feeds; keep an archived replay (gtfsrt.io) so the demo never depends on live uptime.
- **Verdict:** best combined fit on every heavily-weighted criterion.

### D4 — Maritime port congestion & vessel dwell — **STRONG SECOND (highest "wow")**
- **What:** AIS trajectory → geofenced port/berth state → congestion index, dwell/turnaround prediction, AIS data-quality filtering.
- **Strengths:** largest volumes (100M+ messages feasible), strongest data-quality story (AIS is famously dirty), rich user groups (terminal planner, port authority, carrier, shipper, customs).
- **Weaknesses:** bulk-open AIS is **US-only** (MarineCadastre); heavy geospatial state-machine work.
- **Risks:** geofencing/berth reference geometries are often unofficial; AIS cleaning can consume the whole semester. Mitigation: scope to 1–2 US ports with published berth geometry.
- **Verdict:** choose only if the team wants maximum scale and is comfortable with geospatial complexity.

### G1 — Transit feed data-quality observatory — **LEAST-OBVIOUS HIGH-VALUE**
- **What:** Continuously ingest and validate the Mobility Database corpus (6,000+ GTFS/GTFS-RT feeds, 99 countries); score conformance, staleness, schedule-vs-realtime consistency; alert on regressions.
- **Strengths:** unambiguous data engineering (scheduling, backoff, idempotency, versioned storage, at-scale validation); enormous scale; the "product" *is* the pipeline; differentiating in a course context.
- **Weaknesses:** must be framed around user decisions or it reads as self-referential monitoring; less spatio-temporal analytics.
- **Risks:** many feeds are private/broken → filter `authentication_type=none`; validation at scale is compute-heavy.
- **Verdict:** excellent as a **scale layer fused into D1** (one pipeline, two audiences), weaker as a standalone narrative.

### D3 — Aviation network delay propagation
- **Strengths:** BTS On-Time Performance (1987→present, public domain, ~100M+ rows) is a superb warehouse/BI dataset; graph BRs (propagation centrality) are distinctive.
- **Weaknesses:** BTS is US-only and monthly (no streaming); OpenSky historical is application-gated.
- **Risks:** if the OpenSky university request is denied, the trajectory/holding BRs degrade.
- **Verdict:** strong if the team prefers relational/graph analytics over streaming and can secure OpenSky access.

### D5 — Shared-mobility availability & rebalancing
- **Strengths:** real-time (GBFS) + batch (trip history) mixed regime; easy infra; HCMC motorbike-first context makes equity/rebalancing BRs locally novel.
- **Weaknesses:** modest scale (hundreds of stations); GBFS has no history.
- **Verdict:** good but a notch below on rubric breadth.

### D6 / D2 — Road safety; accessibility & equity
- **Strengths:** data is open and rich; many user groups; strong correctness/integration work.
- **Weaknesses:** batch/annual only ⇒ weak streaming story; better used as **enrichment layers** on top of D1 (reliability × safety corridor; accessibility × reliability).
- **Verdict:** not primary; high-value add-ons that also earn the "more user groups" bonus.

### V0 — Vietnam-only batch
- **Strengths:** domain-authentic; zero infrastructure risk.
- **Weaknesses:** no GTFS-RT, no streaming, ~1.5 MB transit core, mostly aggregate PDFs; fails the streaming/Big-Data and depth axes that carry the most rubric weight.
- **Verdict:** **reject as primary**; retain as an enrichment/case-study layer (Hanoi GTFS, OSM Vietnam, TomTom indices) to add local relevance at low risk.

---

## 4. Leading recommendation

**Primary direction: D1 — Urban transit reliability & service-quality intelligence**, executed as a
streaming + batch lakehouse pipeline, with a **scale/quality layer (G1-lite)** and an optional
**Vietnam case-study layer (V0)**.

**Mandatory alternative axis (required by spec):** *processing* — **Spark Structured Streaming (micro-batch) vs Apache Flink (event-time)**.
**Recommended second axis (bonus):** *storage* — **Delta Lake on MinIO vs DuckDB-over-Parquet vs BigQuery sandbox**.

**Why this and not the others:** it is the only candidate that scores ≥4 on *every* heavily-weighted
criterion simultaneously — obtainable licensed data, real streaming, mandatory management+processing
technologies, ≥8 demonstrable BRs, five user groups, and two honest benchmark axes with externally
anchored correctness references. D4 has more "wow" but higher obtention and geospatial risk; G1 is
strong but narratively thinner alone; D3/D5/D6/D2 are either batch-only or lower-breadth.

**Combined design (best of D1 + G1 + V0):**
- Core streaming: 2–3 stable GTFS-RT agencies (e.g., MTA keyless subway/LIRR/MNR; plus one European feed) → reliability KPIs.
- Scale/batch: NYC TLC trip records (billions of rows) → lakehouse/partitioning/compaction benchmark arm.
- Quality layer: feed-conformance/staleness scoring (G1-lite) → data-correctness BRs.
- Local layer: Hanoi GTFS + OSM Vietnam + TomTom congestion → Vietnam case study (optional).

---

## 5. Decisions resolved by the owner (2026-09-23)

All decisions below are now locked; they supersede the open questions in the research reports.

| # | Decision | Resolved choice | Consequence |
|---|---|---|---|
| DP1 | **Vietnam framing** | **Hybrid** — international streaming core (MTA GTFS-RT, gtfsrt.io) + Vietnam case study (Hanoi GTFS + OSM + TomTom) | Real streaming + scale, plus localised relevance |
| DP2 | **Runtime host** | **ONE machine — this development host** (ASUS TUF F15; i7-12700H 14C/20T; 31.6 GB RAM; D: ~198 GB free) — **not** four laptops | Single-host resource envelope forces sequential Compose profiles; team uses **Git**, not distributed nodes |
| DP3 | **Managed-cloud arm** | **Local-only, zero cost** (no BigQuery/Redshift/Synapse/Databricks) | Axis B = Delta-on-MinIO vs DuckDB vs ClickHouse; managed arm becomes a *discussed* alternative only |
| DP4 | **Live vs replay** | **Archived real replay** is the canonical path | No 24/7 collector; deterministic, reproducible demo + benchmarks |
| DP5 | **Team skills** | **Python-first** | PySpark + PyFlink with identical logic so Axis A stays fair |

**Data policy (owner, binding):** the core project uses **real** transportation data; synthetic data is
**supplementary only** for scalability/stress experiments and never substitutes for the real dataset used to
demonstrate business requirements. See `PROJECT_PLAN.md` §1.1.

**Runtime policy (owner, binding):** the entire stack runs on **one machine**; benchmarks are
single-machine/local and never presented as distributed-cluster results. See `PROJECT_PLAN.md` §1.2 and §17.4.

---

## 6. Unresolved questions carried forward
1. Final feed selection (2–3 GTFS-RT agencies) pending a stability check over ~2 weeks.
2. OpenSky university access (only relevant if D3 is chosen).
3. Whether the instructor values Vietnam-localisation over technical depth (DP1) — **asked**.
