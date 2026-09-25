# Transportation Domain — Problems, Stakeholders & Data-Engineering Opportunity Map

**Course:** CO5173 Data Engineering (HCMUT) · Sem 1 2026-2027 · **Assigned domain:** Transportation
**Date:** 2026-09-23 · **Companion:** `03-data-sources/vietnam-transportation-data.md`, `03-data-sources/global-open-datasets-and-apis.md`, `01-research/data-engineering-technology-landscape.md`
**Method:** Web research (query fan-out across 18 sub-domains) against primary/authoritative sources; the in-repo VERIFIED data-availability reports are reused. No paywalled or credentialed sources accessed.

> **RECOVERY & VERIFICATION NOTE (added 2026-09-23 during audit).**
> This report was recovered from the execution log of an interrupted research subagent; the original
> artifact on disk was a 1,287-byte skeleton and the full body never persisted. The recovered content
> is reproduced here. During recovery, the two claims that most affect the ranking were independently
> re-verified against primary sources:
> - **NOAA MarineCadastre AIS bulk (D4 feasibility) — CONFIRMED.** Bulk download at `marinecadastre.gov/ais`
>   and the AccessAIS / Marine Cadastre Hub tools; 2024 and 2025 **GeoParquet** vessel-traffic files exist
>   (`hub.marinecadastre.gov`; `github.com/ocm-marinecadastre/ais-vessel-traffic`). US broadcast-point vessel
>   traffic, open. (Searched 2026-09-23.)
> - **OpenSky historical access gating (D3 feasibility) — CONFIRMED.** Trino historical SQL interface is
>   `"available to university-affiliated researchers"` (`openskynetwork.github.io/opensky-api/trino.html`;
>   `opensky-network.org/about/faq` — institutional researchers may request unlimited/historical access),
>   plus a complete Trino-table snapshot dataset dated 1 March 2026 (`opensky-network.org/data/scientific`).
>   So D3 is feasible *only if* the HCMUT data request is approved (currently an open risk, not a blocker).
> - **Cross-checked against sibling reports — NO CONTRADICTIONS.** MDB (6,000+ feeds / 99 countries),
>   Uber Movement discontinued, TransitFeeds dead, ADS-B Exchange enterprise, MarineTraffic no export,
>   OpenSky non-commercial + gated, OSM ODbL, GBFS real-time-only: all consistent across reports.
> - **Corrections carried in:** TfL has **no bulk historical vehicle-position dump** (own archiving required);
>   Danish AIS keeps only **~24 months** online; GBFS explicitly **excludes** historical/trip data.

## Legend
- **[VERIFIED]** — confirmed against a primary source (URL given).
- **[UNVERIFIED]** — secondary source only, not confirmed this session.
- **[ASSUMPTION]** — analyst inference.
- **[PROPOSAL]** — recommendation for this project.

## 0. Framing and constraints
- Grading floor: **>= 2n business requirements** (n=4 -> **>= 8**), each tied to a business objective and each demonstrable in the running app. **At least one alternative data-engineering solution** must be benchmarked.
- Instructor tech menu: management (Redshift, Hive, Synapse, Cassandra, BigQuery/BigLake, CouchBase, Databricks, Neo4J, RavenDB, DynamoDB, Oracle lakehouse) + processing (Flink, Spark Streaming, Hadoop MR, Storm, Kafka Streams).
- **Selection filter used below:** a sub-domain is strong only if the data is (a) open + bulk/API, (b) genuinely high-volume or streaming (so Kafka/Flink/Spark are justified, not decorative), (c) multi-source (integration is non-trivial), (d) spatio-temporal. Sub-domains that are proprietary, PII-gated, or aggregate-only fail (a) — see §5.
- **Domain-local note:** Vietnam open transport data is thin (no HCMC/Hanoi GTFS-RT, no official HCMC bus GTFS, no transport category on the HCMC open-data portal). A Vietnam-only framing is batch/static. See companion report. **[VERIFIED]**

## 1. Sub-domain sweep

**DE depth** = real acquisition/integration/streaming/modelling load (1–5). **Data for students** = **A** open+licensed+adequate volume · **B** open but thin/static/request-gated · **C** proprietary, paid, PII-gated or ToS-restricted.

| # | Sub-domain | Data-intensive problem | Key user groups (log-in -> decision) | DE depth | Data | Key open sources (primary) |
|---|---|---|---|---|---|---|
| 1 | Urban public transit ops & reliability | Scheduled vs actual service divergence: lateness, earliness, missing trips, bus bunching, headway irregularity; no continuous stop-level truth | Network ops controller (hold/dispatch), scheduler (timetable rewrite), service planner (route/frequency), transit authority (KPI/contract), rider | **5** | **A** | GTFS + GTFS-Realtime (Mobility Database: 6,000+ feeds, 99 countries) |
| 2 | Road congestion / flow / incident detection | Fuse detector, probe and event streams into trustworthy speed/incident state + corridor reliability | Traffic Management Centre operator (signal/ramp control), city DOT, incident response, navigation provider | **5** | **B-C** | Waze for Cities (partner-gated GeoRSS), TomTom/INRIX (paid API); open bulk real-time is scarce |
| 3 | Multimodal journey planning / MaaS | Integrate schedules, real-time availability, fares, payments across operators; interop is the bottleneck | Traveller, city mobility manager, MaaS operator, trip-planner developer | 4 | **A-B** | GTFS, GTFS-RT, GBFS, GTFS-Fares v2, NeTEx/SIRI |
| 4 | Fleet & freight logistics | ETA accuracy, tour/load optimisation, cold-chain & exception management across heterogeneous carriers | Fleet dispatcher, 3PL control tower, shipper, driver | **5** | **C** | Effectively proprietary (TMS/telematics); no open bulk source |
| 5 | Ride-hailing / shared mobility / micromobility | Dock/vehicle availability supply-demand imbalance; rebalancing; modal shift measurement | City mobility manager (permit conditions), operator ops (rebalancing), rider | 4-5 | **B** | GBFS (real-time, open); Citi Bike trip history (bulk, monthly) |
| 6 | Air transport (delays, airspace, airport ops) | Delay propagation across aircraft/crew/airport network; turnaround; holding; disruption recovery | Airline ops/network planner (retime, swap, cancel), airport ops (gate/stand), ANSP/ATM (flow), passenger | **5** | **A** | BTS Airline On-Time Performance (1987-present); OpenSky ADS-B (API + Trino + curated datasets) |
| 7 | Maritime / port logistics | Berth-to-berth congestion, vessel dwell, anchorage queues, landside hinterland flow | Terminal ops planner (berth/crane), port authority, carrier (schedule), shipper, customs | **5** | **A-B** | NOAA MarineCadastre AIS (US, bulk); Global Fishing Watch presence; Mendeley 11-port AIS sets; OECD AIS dashboard |
| 8 | Rail freight | Wagon/consist tracing, terminal dwell, path/allocation reliability | Rail ops controller, terminal planner, shipper | 4 | **C** | Mostly commercial; limited gated European feeds |
| 9 | EV charging | Charge-demand forecasting, charger placement, queue/uptime, grid impact | CPO network planner, DNO/grid planner, fleet operator, driver | 4 | **A-B** | Open Charge Map (bulk snapshots), UrbanEV (Shenzhen), ACN-Data (Caltech/JPL) |
| 10 | Road safety / accidents | Micro-location risk factors, severity modelling, countermeasure prioritisation | Road-safety engineer, city DOT (Vision Zero), police, insurer, advocate | 4 | **A** | NHTSA FARS (1975-present) + CRSS; city Vision Zero portals |
| 11 | Parking / curbside | Occupancy & turnover prediction; dynamic pricing; loading-zone conflict with delivery | City curb manager (pricing/rules), parking operator, driver, courier | 4 | **B** | SFpark historical occupancy/payment; scattered municipal sensor sets |
| 12 | Fare / ridership analytics | OD inference from entry-only taps, load profiles, revenue/evasion, demand elasticity | Revenue & finance, service planning, fare-policy analyst | 4-5 | **B-C** | MTA subway hourly ridership + new OD dataset (public); raw AFC mostly PII-gated |
| 13 | Predictive maintenance (fleets) | Fault-code/telematics-driven failure forecasting; parts & shop scheduling | Fleet maintenance manager, depot planner | **5** | **C** | Public labelled fleets essentially absent (industrial blogs concede this) |
| 14 | Emissions / sustainability | Link-level activity x emission factors -> inventory; congestion/scenario effects | Environment dept, transport planner, ESG/air-quality analyst | 4 | **A-B** | COPERT (EU, free), HBEFA (licensed), FHWA HPMS, OSM road network |
| 15 | Transit equity / accessibility | Isochrone access to jobs/services by population segment; Title VI gap analysis | Equity officer, MPO/planning authority, NGO/advocate, elected official | 4 | **A** | GTFS + census/demographic grids + OSM (all open) |
| 16 | Ferry / waterborne urban transit | Schedule adherence and capacity on sea/river routes with low-frequency, high-variance service | Ferry ops controller, terminal manager, island/coastal community, DMO | 4 | **A-B** | NYC Ferry, Washington State Ferries, BC Ferries GTFS/GTFS-RT |
| 17 | Paratransit / demand-responsive (DRT) | Trip-booking feasibility, on-time performance, provider brokering, no-show prediction | Agency DRT manager, broker, rider, care provider | 4 | **C** | PII-gated; GTFS-Flex only partially published |
| 18 | Intercity coach / long-distance bus | Network coverage, fare/availability volatility, punctuality on trunk corridors | Operator revenue manager, passenger, regulator | 3 | **C** | No open feeds; scraping = legal risk |

**Read-out.** Rows **1, 3, 6, 7, 15** combine high DE depth with data students can actually obtain. Row 2 is the most *visible* transportation problem but its real data is gated (a trap). Rows 4, 5(sort of), 8, 13, 17, 18 fail the obtainability filter as raw inputs. Row 10 is a strong, under-rated option (§2.6). Row 16 is the least-obvious genuinely-open niche (§4.2).

## 2. Deep dives on top candidates

Each deep dive: problem -> users + the decision each makes -> business objectives -> candidate business requirements (BR) -> data characteristics (5 V's) -> why data engineering is necessary -> caveats. BRs are written to be **demonstrable** in an application and **analytics/BI/DSS/DM-flavoured**, per the rubric.

### 2.1 D1 — Urban transit reliability & service-quality intelligence
**Problem statement.** Agencies publish static schedules and (increasingly) GTFS-Realtime, but the verifiable question "was service actually delivered as promised, where, when and for whom?" is not answered continuously. Lateness/earliness, missing trips, bus bunching and headway irregularity must be reconstructed from noisy high-frequency vehicle positions matched to schedule — a join-and-inference problem, not a reporting problem. **[VERIFIED]** that this is a recognised measurement discipline (MBTA customer-weighted performance from GTFS-RT, TRID 1393881; TRB/SMARTER "Deriving Transit Performance Metrics from GTFS Data", smartercenter.org).
**Stakeholders & user groups**
- *Network operations controller* — decides whether to hold a vehicle, short-turn, or inject a relief bus now.
- *Scheduler / timetable planner* — decides where to add running-time slack and where layover is insufficient.
- *Service planner* — decides frequency/route changes and where reliability justifies investment.
- *Transit authority / contract manager* — decides incentive/penalty and publishes route-level reliability scorecards.
- *Rider-facing analyst* — decides what "departure confidence" to surface per stop/hour.
**Business objectives.** Reduce excess wait time; raise on-time performance; eliminate bunched pairs; make reliability transparent and comparable across routes/periods.
**Candidate business requirements (BR)**
- BR1 Stop- and route-level on-time performance (-1 min / +5 min band), daily/hourly, with confidence from sample coverage. *(Analytics/BI)* — **[VERIFIED]** metric definition in common use (saadiqm.com ETL walkthrough; MBTA methodology).
- BR2 Headway-regularity and **bus-bunching detection** (headway outside +/-20% band; bunched-pair identification). *(Data mining / DSS)* — **[VERIFIED]** AVL-based bunching methodology (Feng et al., PDXScholar).
- BR3 Missing-trip and `NO_DATA` detection: scheduled trips with no plausible observed vehicle (service delivered vs promised gap).
- BR4 Segment-level travel-time distribution and **delay-cause attribution** (dwell vs running vs signal) to separate schedule error from incident.
- BR5 Reliability ranking/scorecard per route-stop-hour with statistical uncertainty (so rankings are defensible).
- BR6 Early-warning: predict which trips are likely to end bunched/late > X min before they finish (streaming feature computation). *(DSS)*
- BR7 Data-quality monitor for the realtime feed itself (stale timestamps, implausible jumps, feed gaps) — precondition for trusting BR1–BR6.
- BR8 Rider-facing "departure reliability" explorer at stop level for the next hour. *(BI)*
**Data characteristics.** *Volume:* one trip-update/vehicle-position sample per vehicle per 15–30 s; a mid-size agency is 10^6–10^7 records/day, 10^8–10^9/year. *Velocity:* continuous (spec expects refresh <= 30 s; data should be < 90 s old). *Variety:* protobuf GTFS-RT + CSV GTFS static + optional service alerts/fares. *Veracity:* frequent nulls, teleporting positions, clock skew, feed outages — the hard part. *Spatial:* stop/route/shape geometry; 15–30 m positional noise. *Temporal:* timestamps + service calendars (weekday/weekend/holiday exceptions).
**Why data engineering is necessary.** The metric is not in any source table: it is produced by a streaming join of schedule to telemetry with windowing, late-arrival handling, outlier suppression and stateful trip state machines. Requires Kafka/Flink (or Spark Structured Streaming) + a high-write store (Cassandra/BigQuery) + a serving layer (Redshift/warehouse + BI). A dashboard alone cannot produce it; you must *build* the pipeline. **[PROPOSAL]**
**Caveats.** Realtime feed coverage varies by agency (some only 15 s resolution — a known sampling bias). Without GTFS-RT, D1 degrades to static-only analysis. Some agencies gate realtime feeds to partners; choose feeds after verifying stability. **[VERIFIED/ASSUMPTION mixed]**

### 2.2 D2 — Multimodal accessibility & equity gap analysis
**Problem statement.** Planners must quantify who can reach which jobs/services within a travel-time budget, and whether service changes widen or narrow gaps for protected/low-income populations — requiring GTFS schedules, street network, and demographic grids to be joined into time-dependent isochrones. **[VERIFIED]** as an established research/DSS area (TRB/ROSA "Using GTFS Data to Evaluate and Improve Public Transit Equity", rosap.ntl.bts.gov/view/dot/61594; transit gap index literature).
**Stakeholders & user groups.** *Equity officer* (decides where to prioritise service restoration/extension); *MPO/city planner* (decides corridor investment); *NGO/advocate* (decides which gaps to campaign on, with evidence); *elected official* (decides budget defence); *university researcher* (baseline equity metrics).
**Business objectives.** Maximise access per operating dollar; demonstrate Title VI / distributional compliance; target interventions at highest-access-deficit populations.
**Candidate BRs.**
- BR1 Time-of-day isochrone/anisotropic accessibility surface from any origin set (jobs, clinics, schools) with schedule fidelity. *(analytics/spatial)*
- BR2 Access-deficit ranking: rank zones by (population need x low transit access). *(data mining / DSS)*
- BR3 Equity delta: quantify change in access for protected vs non-protected groups under a proposed or historical service change. *(BI/DSS)*
- BR4 Service-change impact simulator for a candidate timetable (rerun access under edited GTFS). *(DSS)*
- BR5 Multimodal extension: include GBFS micromobility availability in the door-to-door access calculation.
- BR6 Data-quality/completeness score for the demographic + schedule inputs before publishing equity findings.
- BR7 Benchmark vs peer cities across a normalised access index.
**Data characteristics.** *Volume:* GTFS moderate (10^5 stop_times); OSM street network large (10^6–10^7 edges); demographic grids 10^4–10^6 cells. *Velocity:* low (batch/periodic) — a weakness for a streaming-heavy rubric. *Variety:* CSV/GTFS + PBF/SHP/GeoJSON + census CSV. *Veracity:* GTFS validity issues, census tract-boundary changes, OSM completeness bias. *Spatial:* dominant (network topology, projections, CRS pitfalls). *Temporal:* schedule calendars + isochrone time windows.
**Why data engineering is necessary.** Requires large-scale graph processing (routing on schedule-expanded networks = temporal graph), spatial indexing, and incremental recomputation when feeds change. Natural fit for a **graph store (Neo4J)** plus batch processing — good coverage of the instructor's menu. **[PROPOSAL]**
**Caveats.** GTFS alone ignores crowding/reliability; adding D1's reliability makes the access metric defensible ("realizable accessibility"). Findings can be politically sensitive — frame as measurement, not advocacy. ISO 8601 4-char time (>24:00) handling is a classic correctness trap.

### 2.3 D3 — Aviation network delay propagation & disruption analytics
**Problem statement.** Delay is a network externality: a late aircraft, crew or slot in one airport degrades downstream flights. Operations must separate locally-caused from propagated delay, and know which rotations are fragile, using flight-level on-time records plus surveillance tracks. **[VERIFIED]** via BTS Airline On-Time Performance (delays, causes, taxi times, cancellations; data from 1987) and OpenSky ADS-B archives.
**Stakeholders & user groups.** *Airline ops/network planner* (decides retime/aircraft swap/cancel); *airport ops* (decides stand/gate allocation and peak mitigation); *ANSP/flow manager* (decides flow/ground measures); *passenger/IRROPS analyst* (decides rebooking policy); *cargo/forwarder* (decides buffer and routing).
**Business objectives.** Cut propagated delay; improve schedule robustness; raise on-time arrival; reduce passenger misconnect and holding cost.
**Candidate BRs.**
- BR1 Delay-cause decomposition: local (carrier/weather/NAS/security) vs **propagated** delay share per flight/segment. *(data mining / analytics)* — BTS exposes cause codes. **[VERIFIED]**
- BR2 Tail-number (aircraft rotation) chain reconstruction -> identify fragile rotations and turnaround buffer erosion. *(DSS)*
- BR3 Airport/sector **congestion & holding** estimation from ADS-B trajectories (holding patterns, taxi-out excess, level-off detection). *(data mining)* — **[VERIFIED]** methodology exists (TU Delft holding-time prediction using surveillance + weather + delay).
- BR4 Route/airport **network delay-propagation graph** and centrality ranking (which nodes spread disruption most). *(graph / DSS)* — natural Neo4J fit.
- BR5 Probabilistic arrival-delay forecast and its calibration at hub level. *(DSS)*
- BR6 Weather/season covariate attribution for delay clusters.
- BR7 Data-integrity layer reconciling BTS scheduled vs OpenSky observed coverage gaps before any attribution.
- BR8 Disruption-recovery what-if: simulate knock-on effect of cancelling/holding a rotation set.
**Data characteristics.** *Volume:* BTS ~7M+ flights/yr annually; OpenSky state vectors are very large (10^9+ messages/yr across the network). *Velocity:* BTS monthly batch; ADS-B effectively streaming. *Variety:* CSV/relational + ADS-B/Trino + weather + aircraft metadata. *Veracity:* BTS cause codes partly self-reported; ADS-B has coverage holes (measured > 70% but not uniform) and spoofing/non-equipped gaps. *Spatial:* airport/airspace/sector geometry, trajectories. *Temporal:* schedule vs actual, timezone-sensitive (local-time fields), daily/monthly cycles.
**Why data engineering is necessary.** Multi-billion-row trajectory reconciliation, windowed turnaround state, graph propagation — all beyond a spreadsheet or a dashboard; and the deliverable (attribution + forecast) is a pipeline output. **[PROPOSAL]**
**Caveats.** BTS is **US-only, domestic, monthly** — no near-real-time. OpenSky API is rate-limited/credentialed for historical bulk (Trino access is application-gated) — verify access level early. Airport/airspace reference geometries are partly licensed (avoid AIXM/ARINC paywalls).

### 2.4 D4 — Maritime port congestion & vessel dwell analytics
**Problem statement.** Terminals and carriers need to anticipate berth congestion and vessel dwell instead of reacting, using AIS vessel movement fused with berth/port reference data. **[VERIFIED]** as a live research area (Busan dwell-time ML, MDPI JMSE 11(10)1846; OECD AIS vessel-tracking dashboard, oecd.org; vessel-turnaround ML from AIS, Frontiers Future Transportation 2025).
**Stakeholders & user groups.** *Terminal operations planner* (decides berth and crane allocation); *port authority* (decides anchorage/queue policy, infrastructure); *carrier network planner* (decides schedule and port rotation); *shipper/forwarder* (decides buffer, mode shift, stock placement); *customs* (risk triage).
**Business objectives.** Reduce vessel waiting time at anchorage; raise berth utilisation; shorten container dwell; improve schedule reliability and hinterland flow.
**Candidate BRs.**
- BR1 Port/berth **congestion index** (arrivals vs berth occupancy vs anchorage queue) hourly/daily. *(BI/DSS)*
- BR2 **Vessel dwell / turnaround time** prediction by vessel class and berth. *(data mining)* — **[VERIFIED]** precedent exists.
- BR3 Anchorage-wait detection & evolution: identify vessels waiting, duration distribution, pattern shifts.
- BR4 Cargo-flow/port-activity classification by vessel type and inferred commodity group. *(analytics)* — **[VERIFIED]** OECD approach maps AIS to 23 commodity groups.
- BR5 Congestion-to-port-time sensitivity: quantify how queue state changes total time in port. *(DSS)*
- BR6 AIS data-quality/filtering layer (duplicate MMSI, spoofed/AIS-off gaps, speed-vs-position inconsistencies) — mandatory before any BR above. **[VERIFIED]** AIS is described as error-prone/high-volume in the literature.
- BR7 Network view of port-call sequences and chokepoint dependencies. *(graph)*
- BR8 Emissions proxy per port area from vessel time-in-mode (ties to §2.6).
**Data characteristics.** *Volume:* AIS is among the highest-volume public transport feeds — millions of messages/day in one busy region; multi-GB to TB scale archives. *Velocity:* streaming (seconds) with batch archives. *Variety:* NMEA/CSV/Parquet AIS + port/berth GIS + vessel registry metadata. *Veracity:* high — duplicates, MMSI errors, gaps, spoofing. *Spatial:* strong (geofencing, berth polygons, trajectories). *Temporal:* strong (ETA/dwell, seasonality).
**Why data engineering is necessary.** Geofencing + trajectory segmentation + dwell state machines over hundreds of millions of messages is exactly a streaming + geospatial + time-series architecture; nothing here is a stock report. **[PROPOSAL]**
**Caveats.** Only **US waters are bulk-open** (NOAA MarineCadastre — confirmed `marinecadastre.gov/ais`; 2024/2025 GeoParquet). Global AIS is commercial (MarineTraffic/Spire) — avoid. Global Fishing Watch gives presence aggregates (privacy-reduced), not tracks. Port/berth reference geometries may be unofficial. **[VERIFIED]** on MarineCadastre openness; **[ASSUMPTION]** on adequacy of non-US open archives.

### 2.5 D5 — Shared-mobility availability, demand & rebalancing analytics
**Problem statement.** Docked/undocked fleets suffer availability imbalance: empty docks block returns, empty stations block departures, and operators must decide rebalancing moves before demand materialises. Real-time availability plus historical trip records must be combined into station-level demand and imbalance forecasting. **[VERIFIED]** GBFS is the real-time open standard (github.com/MobilityData/gbfs; NCHRP 08-119 factsheet) and Citi Bike publishes bulk monthly trip histories (citibikenyc.com/system-data).
**Stakeholders & user groups.** *City mobility manager* (decides permit conditions, parking/corral siting, equity requirements); *operator ops/rebalancer* (decides truck routes and dock reservations now); *urban planner* (decides protected-lane and station expansion priorities); *rider* (decides whether to attempt a trip).
**Business objectives.** Maximise trip fulfilment and service availability; minimise rebalancing cost/km; prove modal shift and equity of access.
**Candidate BRs.**
- BR1 Station-level **net-flow and imbalance** (depletes/fills) by hour/day-type. *(analytics)*
- BR2 Dock-availability nowcast (short-horizon) and **stock-out risk** alerting. *(streaming DSS)*
- BR3 Rebalancing recommendation: prioritised vehicle moves / pickup-dropoff list with estimated cost. *(DSS)*
- BR4 Demand driver analysis: weather, calendar, transit disruption, events effect on ridership. *(data mining)*
- BR5 OD-flow and **inferred-trip-purpose** mining from trip histories (commute vs leisure corridors). *(data mining)* — **[VERIFIED]** OD-inference from GBFS is documented (arXiv 2010.12006).
- BR6 Equity-of-availability: availability vs income/transit-access by zone. *(DSS/equity)*
- BR7 Fleet-health/utilisation KPI (trips per bike per day, dead mileage from rebalancing).
- BR8 Data-quality gate: GBFS feed conformance/staleness checks before metrics publish.
**Data characteristics.** *Volume:* GBFS = many small JSON documents per minute per city (thousands of station records each); trip archives ~10^6–10^7 trips/yr per large city. *Velocity:* GBFS real-time; trips monthly batch. *Variety:* JSON (GBFS versions differ!) + CSV/Parquet trips + weather + GIS. *Veracity:* schema drift across GBFS versions, station churn, clock issues, e-bike/bike mixing. *Spatial:* stations, free-floating geographies, hex aggregation. *Temporal:* minute (availability) to monthly (trips).
**Why data engineering is necessary.** Two fundamentally different ingestion regimes (micro-batch JSON polling vs bulk history) must be unified into a station-time model, then windowed for imbalance signals — a textbook streaming + batch (lambda/kappa) integration. **[PROPOSAL]**
**Caveats.** GBFS deliberately contains **no** trip-level or historical data — the historical layer needs a separate source (Citi Bike/other municipal programs), which is inconsistent across cities. Free-floating (moped) feeds can be huge and unstable. Municipal MDS data (which does contain trips) is often agency-restricted. **[VERIFIED]** on GBFS scope limits.

### 2.6 D6 — Road-safety risk mapping, severity modelling & countermeasure prioritisation
**Problem statement.** Cities commit to Vision Zero but allocate safety budgets without a defensible, micro-location risk model; crash records must be joined to road geometry, exposure and behavioural factors to separate real hotspots from noise and to evaluate countermeasures. **[VERIFIED]** FARS is a national census of fatal crashes from 1975 with 100+ coded elements (nhtsa.gov FARS; catalog.data.gov), and CRSS provides nationally representative sampled crashes (transportation.gov safety tools).
**Stakeholders & user groups.** *Road-safety engineer* (decides which intersection/segment gets treatment funding); *city DOT/Vision Zero office* (decides corridor programme and speed-limit changes); *police/traffic enforcement* (decides targeting); *insurer/actuary* (decides risk pricing); *advocate* (decides campaign evidence).
**Business objectives.** Reduce fatalities/serious injuries per VKT; concentrate spend on highest-risk locations; demonstrate countermeasure effectiveness.
**Candidate BRs.**
- BR1 **Network-constrained crash hotspot** detection (segment/intersection clustering with exposure normalisation). *(data mining/spatial)*
- BR2 Severity / KSI probability model with covariates (road class, speed, light, weather, user type). *(data mining)*
- BR3 Vulnerable-road-user risk index (pedestrian/cyclist/motorcyclist) by zone. *(BI/equity)*
- BR4 Exposure model: fuse HPMS/traffic counts + OSM network to normalise risk per vehicle-km. *(integration)* — HPMS is free (fhwa.dot.gov/policyinformation/hpms.cfm). **[VERIFIED]**
- BR5 Before/after countermeasure evaluation with control for regression-to-mean. *(DSS)*
- BR6 Risk-factor co-occurrence mining (e.g. impairment x night x rural) for policy design. *(data mining)*
- BR7 Time-series change detection for year-on-year risk shift by corridor. *(DSS)*
- BR8 Crash-record linkage/QA layer (reporting thresholds, geocoding error, 30-day definition) before any modelling. *(DE correctness)*
**Data characteristics.** *Volume:* FARS ~10^6 data points per annual file, 50 years cumulative; CRSS sampled. *Velocity:* annual batch (weak for streaming). *Variety:* fixed-width/CSV relational + GIS + counts. *Veracity:* under-reporting, geocode drift, non-comparable definitions across states/countries. *Spatial:* dominant (linear referencing); *Temporal:* dominant (trend, hour/day/season, daylight).
**Why data engineering is necessary.** Multi-decade multi-source linkage with changing codebooks, network snapping and exposure weighting — genuine integration + warehousing + mining work, and a natural **graph** representation of the road network. **[PROPOSAL]**
**Caveats.** Batch-annual data gives no streaming story; a streaming component must come from an added source (live incident feeds) if the rubric demands it. FARS is **US-only**; Vietnam publishes aggregates only (companion report). Non-fatal crashes require city portals (e.g. NYPD) with inconsistent schemas.

## 3. Comparison and ranking

### 3.1 Trade-off matrix (top candidates)
Scores 1–5 (5 best). **Obtain.** = ease of getting real data now. **DE depth** = genuine engineering load. **Stream** = supports real streaming. **Multi-src** = integration richness. **Rubric fit** = maps to a wide, demonstrable BR set + alternative-solution benchmarking.

| Candidate | Obtain. | DE depth | Stream | Multi-src | Rubric fit | Main risk |
|---|---|---|---|---|---|---|
| **D1 Transit reliability** | 5 | 5 | 5 | 4 | **5** | feed selection/stability |
| **D4 Maritime/port AIS** | 4 | 5 | 5 | 5 | **5** | non-US archives gated |
| **D3 Aviation delay net** | 5 | 5 | 3 | 5 | **4** | US-only, monthly batch |
| **D5 Shared mobility** | 4 | 4 | 4 | 4 | 4 | GBFS lacks history |
| **D2 Accessibility/equity** | 5 | 4 | 2 | 5 | 3.5 | batch-only -> weak streaming |
| **D6 Road safety** | 5 | 4 | 2 | 5 | 3.5 | annual batch; US-only |
| Road congestion (row 2) | 2 | 5 | 5 | 4 | 2 | data gated -> avoid |
| Freight logistics (row 4) | 1 | 5 | 5 | 5 | 1 | data proprietary -> avoid |
| Predictive maintenance (row 13) | 1 | 5 | 5 | 3 | 1 | no public labelled fleet |
| Emissions (row 14) | 3 | 3 | 2 | 4 | 3 | weak streaming; factor DB licence |

### 3.2 Ranked recommendation (>= 8 BRs each achievable)
1. **[PROPOSAL] D1 — Urban transit reliability & service-quality intelligence.** *Primary.* Best combined fit: open, licensed, streaming, multi-source, spatio-temporal, and the metrics genuinely require a pipeline. Instantiates the instructor menu naturally (Kafka/Kafka Streams or Flink ingestion; Cassandra/Dynamo or BigQuery for high-write; Redshift/Synapse/Databricks for serving; Neo4J optional for route graph). Alternative solution is easy and honest: **Flink/streaming-first vs Spark-batch micro-batch**, or **Cassandra vs BigQuery** write path. Reference benchmarks exist (MBTA, TRB) so evaluation criteria are externally anchored.
2. **D4 — Maritime port congestion & vessel dwell.** *Strong second / highest "wow".* Largest volumes, real geospatial time-series, richest data-quality story (AIS is famously dirty). Choose if the team wants to out-scale D1. Risk: verify bulk open archive for the chosen port region before committing (US-only bulk confirmed; non-US gated).
3. **D3 — Aviation delay propagation.** Best if the team prefers relational/graph analytics over streaming; Neo4J network-propagation BRs are distinctive and the BTS dataset is exceptionally well documented. OpenSky historical requires an approved university data request.
4. **D5 — Shared mobility.** Excellent real-time + batch mixing; slightly lower rubric breadth, but equity rebalancing BRs are strong and novel in the HCMC context (motorbike-first city).
5. **D2 / D6** as strong add-on layers rather than primary: both are batch-heavy and better used as enrichment (e.g. D1 + D6 = reliability x safety corridor study; "more interesting business requirements with more user groups" per bonus clause).

### 3.3 How a candidate satisfies the mandatory shape
| Requirement | How D1 (primary) satisfies it |
|---|---|
| >= 8 BRs | BR1–BR8 in §2.1, each demonstrable |
| >= 2 user groups | 5 named user groups with distinct decisions |
| Data mgmt tech | Cassandra/Dynamo (high-write) + Redshift/BigQuery (serving) |
| Data processing tech | Kafka/Kafka Streams or Flink (streaming) + Spark (batch backfill) |
| Alternative solution | batch-only Spark micro-batch + table store vs streaming Flink + wide-column |
| Application | route/stop reliability scorecard, live bunching map, departure-confidence explorer |
| Evaluation | data correctness (BR7 QA gates), performance (latency/throughput bench), exploitation (task success) |

## 4. Least-obvious high-value opportunities

1. **[PROPOSAL] Transit/serving-layer data-quality observatory as the product.** Instead of using a feed, *audit the ecosystem*: continuously ingest hundreds of public GTFS/GTFS-RT feeds from the Mobility Database (6,000+ feeds, 99 countries — **[VERIFIED]**), run the canonical validators, and score feeds on conformance, staleness, realtime-vs-schedule consistency. Users: transit agencies, app developers, MobilityData, funders. It is unambiguously data engineering (scheduling, retries, backoff, idempotency, versioned storage, at-scale validation) and almost nobody builds it as a course project. Business requirements fall out naturally (per-feed scorecards, drift alerts, regression detection). **Caveat:** must be framed around decisions, not as a monitoring tool for its own sake.
2. **Ferry / waterborne urban transit reliability (row 16).** Under-served, low-competition, yet has real GTFS/GTFS-RT (NYC Ferry, Washington State Ferries, BC Ferries). Distinctive mode; same BRs as D1 but with low-frequency, high-variance sea conditions — a genuinely different reliability model. **Caveat:** agency count is small, so benchmarking breadth is limited.
3. **EV-charging reliability & siting as a spatial product.** Open Charge Map bulk snapshots + UrbanEV-style demand + grid context. The least-obvious angle is **charger uptime/queue analysis**, not placement alone. **Caveat:** OCM is crowd-sourced with stale/duplicate records (that *is* the DE problem, but validate before trusting).
4. **Cross-source incident fusion for a corridor** (probe speed + crash records + transit delay + weather). Highly relevant to Vietnamese cities (motorbike-dominant, incident-driven congestion) but each Vietnamese source is aggregate/unofficial — feasible only with a non-VN streaming core and VN as an enrichment case study. **Caveat:** legal/ToS risk on scraping (Decree 147/2024/ND-CP; companion report).
5. **Interoperability/standards conformance product (GTFS <-> GBFS <-> fares).** Build the reference-data and mapping layer that makes multimodal integration possible (fares v2, NeTEx/SIRI alignment), then expose a trip-planning quality metric. True integration work; strong differentiator. **Caveat:** abstract; needs a crisp user decision to justify itself under the rubric.

## 5. Where data engineering would be artificial (avoid)
- **Road congestion / TMC operations as a primary domain** — the interesting data (TomTom/INRIX/Waze) is paid or partner-gated; building a DE system on scraped or missing data is either illegal-ish or a fabricated dataset. Use congestion *indices* (TomTom public dashboard) only as an enrichment feature.
- **Freight / fleet logistics & ride-hailing as primary** — TMS/telematics/trip data are proprietary; any open surrogate is a toy.
- **Predictive maintenance** — no credible public labelled fleet dataset exists; the literature itself names data availability as the blocker. **Flagged: would be fabricated.**
- **Vietnam-only + streaming** — no GTFS-RT, no official HCMC bus GTFS, no transport category on the HCMC open-data portal. Vietnam-only must be batch/static (Hanoi GTFS CC-BY 4.0 ~1.5 MB + OSM + TomTom). **[VERIFIED]**
- **"Live dashboard" as the deliverable** — a dashboard consuming a source table is not a data-engineering system; the pipeline, its correctness and its benchmarks must be the object of study.
- **Aggregate-PDF-only domains** — CAAV/ACV aviation, Vinamarine ports, DRVN, Vietnam Register publish aggregates/news only; DE would be reduced to PDF transcription. **[VERIFIED]**

## 6. Unresolved questions
1. Which specific GTFS-RT agencies will grant stable access without partner agreements, and what are their retention/licence terms for a semester project? Needs feed-by-feed verification.
2. OpenSky historical bulk (Trino) access level for a student project — is it self-service or application-gated? **RESOLVED during recovery:** application-gated to university-affiliated researchers; feasible *if* HCMUT request approved.
3. Confirm a bulk-open AIS archive outside US waters (for D4 relevance to Asia) and its licence. **RESOLVED during recovery:** non-US bulk AIS is commercial/gated; US (MarineCadastre) is the bulk-open option.
4. GBFS version fragmentation: how many target-city feeds are on current versions, and is historical availability archived anywhere for free?
5. Whether the instructor accepts an international dataset core with Vietnam as a case-study layer, or expects Vietnamese data as the primary source. **This decision gates D1/D4 vs a weaker Vietnam-only design.**
6. For D1, does the rubric require *near-real-time* demonstration live in the app, or is archived streaming-level data sufficient for replay?
