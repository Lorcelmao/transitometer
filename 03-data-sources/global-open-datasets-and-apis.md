# Global Open Transportation Datasets and APIs — Data Availability Verification

**Course:** CO5173 Data Engineering (HCMUT) · **Project:** Transportation data pipeline (4 students) · **Date:** 2026-09-23
**Method:** Primary-source probing (HTTP fetch of portals, live API calls, official docs) plus web search. No paywalled or credentialed source was purchased. Each entry states how it was checked.

## Legend
- **[VERIFIED]** confirmed this session against a primary/official source (URL plus observed behaviour).
- **[PARTIAL]** exists and is open, but a specific claim (quota, scale, licence) rests on vendor docs or secondary sources only.
- **[UNVERIFIED]** reported by secondary sources; not confirmed against a primary source this session.
- **[DEAD/RESTRICTED]** confirmed gone, paywalled, or too restrictive for coursework.

## Verdict (read first)
**A fully open, zero-cost, high-scale project is achievable.** Best core: (1) **NYC TLC trip records** (free Parquet, billions of rows, batch); (2) **BTS Airline On-Time Performance** (1987-present, free CSV, batch); (3) **MTA GTFS + GTFS-Realtime** (free, keyless since 2025, streaming); (4) **TfL Unified API** (free key, 500 req/min, batch + micro-batch); (5) **Mobility Database** (catalogue of 6,000+ GTFS feeds, batch ingestion at scale); (6) **gtfsrt.io** (pre-built Parquet archive of US GTFS-RT, streaming analytics without running a collector). Enrich with **OpenStreetMap/Geofabrik**, **Open-Meteo**, and **NOAA / Aviation Weather Center**.

**Hard traps (do not plan around):** Uber Movement **discontinued**; TransitFeeds / OpenMobilityData **dead (Dec 2025)**; ADS-B Exchange and MarineTraffic now **paid/enterprise**; HERE is **credit-card/enterprise**; OpenSky is free but **non-commercial and history gated**; Danish AIS keeps only ~24 months online.

**Licence caution:** several strong datasets are non-commercial or share-alike (OpenSky non-commercial ToU; OSM ODbL; Open-Meteo CC-BY NC on the free tier). All are fine for coursework, but any published artifact must attribute and respect non-commercial terms.

## 1. GTFS / GTFS-Realtime standards and aggregators
The dominant open transit standard. Static = zipped CSV text files; realtime = Protocol Buffers (GTFS-RT) with three entity types: trip updates (tu), vehicle positions (vp), service alerts (sa).

| Source | URL | Access | Auth | Format | Coverage | Verified |
|---|---|---|---|---|---|---|
| GTFS spec | gtfs.org | docs | none | spec | global | VERIFIED |
| MDB catalogue (JSON source of truth) | github.com/MobilityData/mobility-database-catalogs | git clone | none | JSON | 99 countries | VERIFIED |
| MDB CSV snapshot | files.mobilitydatabase.org/feeds_v2.csv | bulk download | none | CSV | 6,000+ feeds | VERIFIED (per official issue) |
| MDB Search API | mobilitydatabase.org | REST | free account to get key | JSON | 99 countries | VERIFIED (portal states sign-up for API) |
| Transitland | transit.land | API + Datastore | free API key | JSON, GTFS | ~2,500 operators | PARTIAL |
| TransitFeeds / OpenMobilityData | transitfeeds.com | DEAD | - | - | history migrated to MDB Dec 2025 | VERIFIED (site banner) |

**Mobility Database** replaces TransitFeeds. Updates: feeds fetched and stored daily at midnight UTC; every feed is validated with the Canonical GTFS Validator, so data-quality signals are already computed (feeds_v2.csv carries extracted features + status). Historical GTFS Schedule versions are retrievable **after 2024-02-08**; older history came across with the TransitFeeds migration.
- Schema: CSV/JSON feed record (mdb id, producer, location, urls, authentication_type, features, bounding box).
- **Data-engineering value:** perfect for a batch ingestion exercise at scale (6,000 feeds: download, validate, parse, load, join against GTFS-RT). Feed quality varies wildly = real data-quality work.
- Reproducibility risk: URLs churn; 403/CAPTCHA on some agency endpoints; some feeds are private (need auth) = filter authentication_type=none.

## 2. GTFS-Realtime archives (real streaming turned into batch)
Real streaming volume without running a 24/7 collector.

- **gtfsrt.io** (by Jarvus Innovations) - **VERIFIED live**. Continuously-updated archive of US GTFS-RT feeds. Two surfaces, both **no auth**:
  - Parquet (compacted daily): http://parquet.gtfsrt.io/<feed_type>/date=<date>/base64url=<b64url>/data.parquet - Hive-partitioned, queryable directly with DuckDB httpfs or Polars.
  - Raw protobuf: http://protobuf.gtfsrt.io/<feed_type>/date=<date>/hour=<ISO_HOUR>/base64url=<b64url>/<ts>.pb
  - Evidence: bucket listing returned HTTP 200 with key `feeds.parquet`, LastModified 2026-09-23T05:11:40Z; protobuf host returns 403 on listing (bucket exists, listing denied). Site states no authentication required. Code AGPL-3.0.
  - Companion: gtfsrt-sandbox (dbt + DuckDB models, TIDES-compliant). Excellent for a streaming-to-lakehouse story without infrastructure.
- **Bus Observatory** - public archive of real-time vehicle movements worldwide (busobservatory.com). PARTIAL (listed by gtfs.org; not probed).
- **CapMetrics** - historical Austin CapMetro vehicle locations. PARTIAL.
- **Self-collect** (if you want your own pipeline): Metropolitan-Council/gtfs_rt_tools (download + parse .pb to CSV), public-transport/gtfsrdb (archive GTFS-RT to SQLite/Postgres). Both open-source; you supply the feed URLs from MDB.
- Sampling/quality: GTFS-RT snapshots are state, not deltas; dedupe on (feed, entity id, timestamp); expect gaps when agencies go down. Polling faster than the agency refresh (~5-30s) adds no information.

## 3. United Kingdom — TfL and London open data
**TfL Unified API - VERIFIED.** Developer portal api-portal.tfl.gov.uk; API root api.tfl.gov.uk.
- Auth: none for ~50 req/min; a **free** subscription product gives **500 requests/min** via `app_key` (query param or header; app_id no longer required).
- Terms cap traffic at **500 calls/min per feed**; TfL reserves the right to throttle. Free to use with attribution.
- Coverage: London - Tube, bus, DLR, Overground, Elizabeth line, tram, river, cable car, Santander Cycles.
- Useful endpoints: /Line/Mode/{modes}/Status, /Mode/{mode}/Arrivals, /StopPoint/*, /Line/{id}/Timetable/{from}, /Journey/JourneyResults, /Occupancy, /Road (traffic disruptions), /BikePoint (cycle hire).
- Temporal: strong real-time + near-real-time; **no bulk historical vehicle-position dump** - history requires your own archiving. Static/live downloads also at TfL Open Data (tfl.gov.uk/info-for/open-data-users/): timetables, cycle hire, road counts, ODS.
- **Fit:** best single on-demand-API-plus-quota-discipline teaching source; pairs well with a scheduler and caching layer (TfL explicitly recommends caching).
- Data quality: generally high; occasional API latency; the free key is rate-limited per key, so one team key suits a demo but not high-frequency polling.

## 4. New York City
The richest single-city open data stack in the world.

- **TLC Trip Record Data - VERIFIED.** nyc.gov/site/tlc/about/tlc-trip-record-data.page. Monthly **Parquet** for Yellow taxi, Green taxi, For-Hire Vehicle (FHV) and High-Volume FHV (Uber/Lyft). Fields: pickup/dropoff datetime, zones, distance, itemized fares, passenger count, payment type, driver pay. Data dictionary PDFs provided.
  - Scale: hundreds of millions of trips per year; total corpus is **billions of rows, tens of GB** (well beyond a laptop) - ideal for Spark/DuckDB/partitioning exercises.
  - Auth: none. Cost: free. Licence: NYC Open Data terms (open, attribution); TLC warns it publishes records as submitted and cannot guarantee accuracy.
  - Quality: known outliers (negative fares, zero distance, extreme speeds, zone 264/265 = unknown) = genuine cleaning work.
  - Lag: monthly, ~2 months. Historical back to ~2009 (yellow) and 2013+ for others.
- **NYC Open Data (Socrata) - VERIFIED.** data.cityofnewyork.us. Free REST/SoQL API (optional app token raises limits). Transport datasets: Motor Vehicle Collisions (NYPD), Traffic Speeds (real-time), Automated Traffic Volume Counts, Bus Stop Shelters, and more. JSON/CSV/GeoJSON.
- **MTA GTFS + GTFS-Realtime - VERIFIED.** api.mta.info and mta.info/developers. **Subway, LIRR, Metro-North and service alerts in GTFS-RT are now available with NO account or API key** (official wording: Accounts and API keys are no longer required). Static GTFS (regular + supplemented) plus documented protobuf extensions.
  - **Bus** real-time still needs a key: gtfsrt.prod.obanyc.com/{tripUpdates,vehiclePositions,alerts}?key=... (bt.mta.info; key free, issued in ~30 min).
  - Cadence: subway RT refreshed ~every 30s; bus endpoints roughly 30s.
  - Formats: GTFS-RT protobuf (custom extensions). Update docs: mta.info/developers (page dated 2026-09-21).
- Also on NYC Open Data: **MTA subway/bus hourly ridership** and turnstile data - great batch join keys against GTFS.

## 5. United States federal — BTS, FHWA, FARS, NHTS
- **BTS Airline On-Time Performance - VERIFIED.** transtats.bts.gov/ontime. Free; **US Government work / public domain**.
  - Coverage/time: first year **1987**, present, **monthly**; 17 US carriers (at least 0.5 percent of domestic revenue). Query tool shows data through **July 2026**.
  - Fields: scheduled vs actual dep/arr, delays, cancellations, diversion, taxi-in/out, air time, distance, delay causes; separate Marketing vs Reporting carrier tables.
  - Access: on-screen plus Download (select fields) from TranStats. No key.
  - Quality: mostly clean; carrier-merger discontinuities (see BTS notes) and occasional late/revised months.
- **FARS (Fatality Analysis Reporting System) - VERIFIED.** nhtsa.gov/FARS; bulk at ftp.nhtsa.dot.gov/FARS. **1975-present**, annual, 170+ coded elements per fatal crash; formats SAS / sequential ASCII / SQL. Public domain (usa.gov PD label). Coverage: 50 states + DC + PR. No PII. Small (MBs) - good for schema/geo modelling, not for scale.
- **FHWA** - HPMS (Highway Performance Monitoring System) and **Traffic Volume Trends** (monthly counts from continuous count stations) via highways.dot.gov / fhwa.dot.gov. Free, national. PARTIAL (portal pages verified; bulk-download mechanics vary by product).
- **NHTS** - National Household Travel Survey (FHWA/ORNL), nhts.ornl.gov. Free microdata for survey years (2001/2009/2017/2022+). PARTIAL (periodic survey, not continuous).
- Note: FARS/NHTS/FHWA are **annual or survey-frequency** - use for enrichment/analytics, not streaming.

## 6. Aviation — OpenSky, FAA, AeroAPI, ADS-B Exchange
- **OpenSky Network - VERIFIED (free, but restricted).** REST API opensky-network.org/api; docs openskynetwork.github.io/opensky-api. Auth via OAuth2 client credentials (free account). Rate limit is a **credit** system: Anonymous 400 credits/day; Standard registered 4,000/day; Active feeder 8,000/day; Licensed 14,400/hour. /states/all cost scales with bounding-box area (global ~4 credits per call at the highest band).
  - Anonymous: live only, 10s resolution, archived `time` ignored. Authenticated: last 1 hour only. Tracks: max 30 days back. **Bulk history (more than 1h) goes through Trino/MinIO and is granted to university-affiliated researchers, government and aviation authorities** - exactly our case (HCMC university), so submit a data request.
  - ToU: **non-commercial / research only**; commercial use (including internal for-profit) prohibited. The **Aircraft Metadata Database** is downloadable as CSV. Scientific datasets (COVID-19 flight set, weekly 24h state vectors, LocaRDS) are published on the site.
  - Domain caveat: OpenSky has **no schedules, delays, cancellations or passenger numbers** - positions only.
- **FAA - VERIFIED.** FAA SWIM is the operational feed (enterprise, not open). Open, free, no-key aviation weather via the **Aviation Weather Center API** (aviationweather.gov/data/api): METAR/TAF/PIREP/SIGMET/G-AIRMET, global METAR/TAF, JSON/GeoJSON/CSV/XML. FAA also publishes NAS status and airspace data. Raw ADS-B is available mainly through universities and industry programs, not as one open API.
- **FlightAware AeroAPI - VERIFIED (limited free).** flightaware.com/commercial/aeroapi. Personal/Academic use is free with a **free starter tier (~500 queries/month, ~5 queries/min)**; commercial from ~$25-100+/mo. History on the free tier is short (~2 weeks); deep history is paid. The AeroAPI **Personal licence explicitly allows academic research with attribution** but forbids redistribution and backfilling other providers. Firehose (streaming) is enterprise-only.
- **ADS-B Exchange - NO LONGER FREE; now enterprise.** adsbexchange.com/api. Owned by JETNET (acquired Jan 2023). Products are **ongoing subscriptions with minimum annual commitments**; historical backfills (up to 10 years) and gRPC streaming are **subscriber-only**; the site states it does not offer one-time data extracts or project-based access. Only a low-cost **Community API via RapidAPI (~$10/mo, 10,000 requests)** exists for personal/non-commercial use. **Do not plan around a free ADS-B Exchange.**
- Trap: Flightradar24 has no free API (credit packs from ~$9/mo, history 2016+). AviationStack / AirLabs / AeroDataBox free tiers are tiny (<=1,000 req/mo) and schedule-grade.

## 7. Maritime — AIS and port data
- **Danish AIS (Danish Maritime Authority) - VERIFIED (free, but windowed).** dma.dk AIS page: historical AIS free, delivered as **zipped CSV**; live/online access via an annual subscriber fee. Policy: the online system keeps **up to 24 months**; older data is archived and opened for a limited period. Files historically at **ftp.ais.dk/ais_data**. Jurisdiction moved to the Danish Emergency Management Agency. A Figshare mirror of 2017/2018 samples exists (e.g., 3.55 GB for Jan 2017) - realistic scale: **millions of position messages per day**, high-frequency point data.
  - Fit: superb for a maritime streaming-analytics or geo/timeseries batch project. Caveats: AIS is unvalidated self-reported data (spoofing, gaps, duplicate MMSI); reuse under the Danish PSI act; verify the current download window before relying on it.
- **Global Fishing Watch - VERIFIED (free with token).** api-doc.globalfishingwatch.org; v3 REST plus R/Python SDKs and **Bulk Download**. Free API token. Products: AIS **fishing effort**, **vessel presence**, **events** (fishing, encounters, loitering, port visits), vessel identity (AIS + 40+ registries). Near-real-time with a **~72h delay**; global and regional; GeoTIFF/CSV/JSON. A **Data Download Portal** holds stable, publication-tied datasets. Free and open; respect licence/rate limits and citation.
- **MarineTraffic (Kpler) - RESTRICTED.** marinetraffic.com. Free tier = coastal live map only, **no data export**; Basic $10/mo gives only **5 export rows / 3-day history**. Historical positions (5 years) and the API are **Enterprise**. Not viable for coursework.
- **Port data:** IMF PortWatch publishes free daily port and chokepoint activity (public API). PARTIAL (verify current endpoint). UNCTAD / World Bank port throughput is aggregate PDF/indicator data only. **VesselAPI** offers a 150 calls/month free tier (positions). NOAA and EMODnet (EU) marine data is environmental, not vessel tracks.

## 8. Micromobility — GBFS, Citi Bike, Divvy
- **GBFS - VERIFIED.** gbfs.org; spec v3.0 current (v3.1-RC3 in release candidate). **Real-time JSON only; the spec explicitly excludes historical/trip data.** Auth: by design **no authentication** (MobilityData states that requiring auth is not compliant with the specification). System catalogue: **systems.csv** on GitHub - **1,500+ shared systems** worldwide (bikes, scooters, mopeds, cars).
  - Files: gbfs.json (discovery), station_information, station_status, free_bike_status / vehicle_status, vehicle_types, system_information, geofencing_zones. Rotating vehicle IDs limit tracking.
  - **Citi Bike** (NYC): citibikenyc.com/system-data - **GBFS real-time feed** plus **monthly trip history CSV** (batch). Divvy (Chicago) also publishes GBFS and monthly trip history.
  - **Aggregators:** api.citybik.es (free, no key) mirrors GBFS for many networks (for example Divvy); the Mobility Database also catalogs GBFS feeds. Scraper marketplaces exist but are unnecessary.
  - Fit: ideal lightweight **streaming** source (poll every 30-60s, tiny JSON) - good for Kafka/Spark Streaming demos on a laptop. Scale is modest (hundreds of stations per city), so treat it as a streaming-pattern source, not a Big Data source. Monthly trip-history CSVs add batch volume.

## 9. Road traffic — HERE, TomTom, OSM, Uber Movement
- **Uber Movement - DEAD.** Discontinued (uber.com decommissioning page; QGIS tutorials now note it is discontinued). Data covered 2016-2020 only, archive-only. **Do not rely on it.**
- **OpenStreetMap / Geofabrik - VERIFIED.** download.geofabrik.de. Daily-refreshed extracts, **ODbL 1.0** (attribution + share-alike). Sizes observed 2026-09: US 11.3 GB, North America 18.0 GB, Europe 32.5 GB, Asia 15.1 GB; **planet ~100 GB compressed / ~2 TB uncompressed**. Formats: .osm.pbf, .gpkg.zip, .shp.zip, .osc.gz deltas. Full contributor metadata is contributor-only (GDPR). Best free geo backbone; pairs with OSMnx/PostGIS.
- **TomTom - VERIFIED (thin but real free tier).** docs.tomtom.com/pricing. **No credit card required**; free monthly requests **per API** (Traffic Incidents 2,500/mo; Traffic Flow and Incidents vector tiles 200,000/mo; Routing 20,000/mo; Map Display 200,000/mo). Traffic Flow is updated **every minute**; global (235+ countries, Orbis Maps). Overages are blocked, not billed. Fit: small-scale real-time traffic sampling, with a commercial-attribution requirement.
- **HERE - RESTRICTED.** The HERE Platform/Traffic API is credit-card/enterprise oriented with a limited evaluation tier; there is no durable generous free tier comparable to TomTom. Treat as paid.
- Other traffic: the TomTom Traffic Index publishes city congestion dashboards and advertises hourly CSVs per city, but vendor pages returned 503 during earlier testing - treat availability as flaky. Country-level road count data varies by authority.

## 10. Europe — EU portal, Eurostat, Copernicus, rail operators
- **transport.data.gouv.fr - VERIFIED (best European aggregator).** French National Access Point. **479 public-transit datasets**, 152 vehicle-sharing, 38 road, 31 bike, plus carpooling/charging. Formats: GTFS, GTFS-RT, NeTEx, SIRI/SIRI-Lite, CSV. Licences mostly **Licence Ouverte (Etalab)**. Public **API** for dataset lists plus validation tools. No auth for most downloads. A strong MDB-equivalent for France, with live real-time feeds (for example Nantes Naolib, Amiens Ametis, Chamonix).
- **Eurostat - VERIFIED.** ec.europa.eu/eurostat, Transport theme. Free, EU-wide, harmonised annual/quarterly statistics (rail, road, maritime, air, inland waterways) via web plus an **SDMX/REST/JSON-stat API**. Caveat: some tables update slowly (the railway passenger table observed covers 2005-2020) - check table freshness before use.
- **EU Open Data Portal (data.europa.eu) - VERIFIED.** Aggregates national and EU catalogues (1.5M+ dataset pages cited); carries the SNCF API-theorique-et-temps-reel record. Metadata plus distributions - useful for discovery; freshness varies.
- **Copernicus CDS - VERIFIED.** cds.climate.copernicus.eu. Free and open, requires a **free account plus a CDS API token (cdsapi)**; **CC-BY** licence. ERA5 hourly **1940-present**, ERA5-Land **1950-present**, plus marine/atmosphere stores. Very large (TB-scale) - good for weather enrichment and for a big-data batch. Watch: ECMWF announced some products (ERA5T, CAMS greenhouse gases) moving to fee-based dissemination - verify before depending on paid-tier products.
- **Rail operators:** SNCF has data.sncf.com open data plus a freemium theoretical/real-time API (the data.gouv.fr record was last updated 2020 - treat as stale; prefer transport.data.gouv.fr feeds). Germany DB official APIs are partner/paid (a community Unofficial DB API exists but is unsupported). Trenitalia has no official open API (ViaggiaTreno is community/unsupported). Note as restricted.

## 11. Contextual data — Open-Meteo, NOAA
- **Open-Meteo - VERIFIED.** open-meteo.com, api.open-meteo.com. **No API key, no sign-up.** Free tier: **<10,000 calls/day, 5,000/hour, 600/min, 300,000/month**, **non-commercial only**, data **CC-BY 4.0**. Forecast up to 16 days; **historical weather from 1940**; historical forecast archive from 2021; marine/air-quality/flood APIs. Source code is AGPLv3 - self-host for unlimited calls. Ideal weather join key for transport delays.
- **NOAA - VERIFIED.** NCEI free bulk plus the **NCEI Access Data Service API** (for example the Global Hourly dataset, CSV, no key). ASOS 1-minute and 5-minute surface observations from **~900 US stations**, 1-minute back to 1998; aviation weather via the **Aviation Weather Center API** (METAR/TAF, global, JSON/GeoJSON/CSV, no key). Public domain. The Iowa Environmental Mesonet (mesonet.agron.iastate.edu) offers a convenient ASOS/METAR download interface and archive.
- Fit: both are free, stable, high-frequency enrichers for delay/incident analysis (for example weather vs BTS delay causes vs MTA GTFS-RT).

## 12. Large-scale candidates for Big-Data benchmarking
Candidates that can plausibly produce 10^8-plus rows / tens of GB, justifying a big-data stack (Spark, DuckDB-on-Parquet, partitioning, compression):

| Dataset | Approx scale | Format | Batch/Stream | Status |
|---|---|---|---|---|
| NYC TLC trip records | billions of trips; tens of GB; ~200M+/yr | Parquet/CSV monthly | batch | VERIFIED |
| BTS On-Time Performance | ~100M+ flight records since 1987 | CSV (selected fields) | batch | VERIFIED |
| OpenStreetMap (Geofabrik US/Europe/planet) | 11-32 GB extracts; planet ~100 GB | osm.pbf | batch | VERIFIED |
| gtfsrt.io US GTFS-RT archive | millions of RT records/day; Parquet by date | Parquet + .pb | batch-on-stream | VERIFIED |
| Danish AIS | millions of position messages/day; GBs/day | zipped CSV | stream then batch | VERIFIED |
| Mobility Database GTFS corpus | 6,000+ feeds; GBs | CSV/zip | batch | VERIFIED |
| Copernicus ERA5 / ERA5-Land | TB-scale reanalysis | NetCDF/GRIB | batch | VERIFIED |

Note: these are throughput estimates. TLC is batch-only; for true per-second streaming you need live GTFS-RT (MTA/TfL), GBFS, or a self-collected AIS/ADS-B feed. gtfsrt.io and self-collected .pb archives are the pragmatic bridge from streaming to batch.

## 13. Traps: dead, paywalled, or too restrictive
| Claimed source | Status | Evidence |
|---|---|---|
| Uber Movement | **DISCONTINUED** | uber.com decommissioning page; QGIS tutorial notes discontinued; data 2016-2020 only |
| TransitFeeds / OpenMobilityData | **DEAD (Dec 2025)** | transitfeeds.com banner; MDB FAQ: replaces TransitFeeds, history migrated Dec 2025 |
| ADS-B Exchange free API | **GONE, now enterprise** | adsbexchange.com/api: min annual commitments, subscriber-only history; licence forbids redistribution |
| MarineTraffic free data | **NO export** | plans page: free = live map only; export restricted to paid |
| HERE traffic API | **RESTRICTED** | credit-card/enterprise evaluation, not a durable free tier |
| OpenSky full history | **GATED** | free ToU non-commercial; history beyond 1h via Trino for university/government only |
| FlightAware Firehose | **ENTERPRISE** | custom licensing, not self-serve |
| data.gov.vn (VN national portal) | **UNRELIABLE** | DNS/SSL problems observed (see sibling Vietnam report) |
| Uber/Grab proprietary APIs | **PARTNER-ONLY** | OAuth2 with partner credentials; no open consumer data |
| Kaggle mirrors of TLC | **SECONDARY** | convenient but not authoritative; prefer nyc.gov originals for reproducibility |

Also verify before use: TomTom Traffic Index CSVs (pages occasionally 503); SNCF real-time API record (stale since 2020); Eurostat table freshness varies.

## 14. Ranking — best picks for a 4-student DE project
Ranked for a 4-student HCMUT team, free-only, by feasibility x scale x data-engineering value:

**Tier 1 - core pillars (pick 2-3):**
1. **NYC TLC Trip Records** - huge, free, Parquet, zero auth, real cleaning work. Best batch/scale pillar. VERIFIED.
2. **BTS On-Time Performance** - 1987-present, free, CSV, clean schema; classic warehouse/BI target. VERIFIED.
3. **MTA GTFS + GTFS-Realtime** - free and now key-less for subway/rail/alerts; genuine streaming. VERIFIED.
4. **Mobility Database** - 6,000+ feeds: ingestion-at-scale plus validation. VERIFIED.

**Tier 2 - streaming / enrichment (pick 1-2):**
5. **TfL Unified API** - free 500 req/min, well documented, forces caching/quota design. VERIFIED.
6. **gtfsrt.io** - GTFS-RT analytics results without running a collector. VERIFIED.
7. **Open-Meteo + NOAA/AWC** - free no-key weather joins. VERIFIED.
8. **OpenStreetMap / Geofabrik** - free geo backbone (ODbL). VERIFIED.

**Tier 3 - specialised (only if the theme demands it):** Danish AIS (maritime), Global Fishing Watch (maritime, token), GBFS/Citi Bike/Divvy (micromobility, streaming), Copernicus (climate enrichment), Eurostat (EU context).

**Avoid as a primary pillar:** Uber Movement, TransitFeeds, ADS-B Exchange, MarineTraffic, HERE, FlightAware Firehose, and OpenSky history (unless the university data request succeeds).

**Suggested architecture fit:** Kafka (or Redpanda) ingesting MTA GTFS-RT + GBFS + TfL into a Bronze layer (raw .pb/JSON), then Silver (Parquet via DuckDB/Spark), then Gold (delay and reliability KPIs); the batch pillars (TLC, BTS) land in the same lakehouse. All free, all reproducible from documented URLs.

## 15. Licence and reproducibility summary
| Source | Licence | Redistribution / caveat |
|---|---|---|
| BTS / FARS / NOAA / AWC | US Government work (public domain) | basically unrestricted |
| NYC TLC / NYC Open Data | NYC Open Data terms | open, attribute; TLC disclaims accuracy |
| MTA GTFS / GTFS-RT | MTA terms | free; follow ToU + attribution |
| TfL Unified API | TfL Transport Data Service terms | free; 500 calls/min/feed cap; attribute |
| Mobility Database catalog | Apache-2.0 (repo) | catalogue free; **feeds keep their own licences** |
| OSM / Geofabrik | **ODbL 1.0** | attribution + **share-alike**; contributor metadata withheld |
| Open-Meteo (free tier) | CC-BY 4.0, **non-commercial** | attribute; no commercial use on free tier |
| OpenSky | proprietary ToU, **non-commercial** | research only; no commercial use |
| Copernicus CDS | CC-BY (variable per dataset) | attribute; some products moving to fee |
| GBFS | per-operator | spec is open; feeds are public by design |
| Global Fishing Watch | GFW terms, free | cite; rate limits apply |
| Danish AIS | Danish PSI act | open reuse; verify current window |
| SNCF / transport.data.gouv.fr | Licence Ouverte (Etalab) | attribution |

Practical rule for coursework: all Tier 1/2 sources are usable, but **attribute** and do **not** imply commercial use where the licence forbids it (OpenSky, Open-Meteo free tier). Keep source URLs plus retrieval dates in the repo for reproducibility.

## 16. Unresolved questions
- Is HCMUT university affiliation sufficient to obtain OpenSky Trino/MinIO bulk history? (requires an explicit data request; approval not guaranteed.)
- Does the current Danish AIS download window still expose full zipped CSVs, or has it narrowed further?
- Exact current Mobility Database API key signup and quota (the portal asks for sign-up; the rate limit is not documented on the public page).
- Transitland free-tier quota, and whether Datastore bulk export is still offered in 2026.
- IMF PortWatch port-activity API current endpoint and limits (not probed this session).
- TomTom free-tier per-day vs per-month semantics (the official page shows monthly; secondary sources show daily) - verify at signup.
- Whether the FlightAware AeroAPI free tier is still ~500 queries/month or the newer 5-dollar free-credit model.

## 17. Limitations of this review
- Verification used HTTP fetch, official documentation, live API responses, and search. **No paid or credentialed source was purchased or logged into**, so quota figures for credentialed sources rest on vendor documentation [PARTIAL].
- Live probing was from a single network on 2026-09-23; some portals (vendor traffic pages, data.gov.vn) were intermittently unavailable and are flagged as such.
- Row/GB estimates are order-of-magnitude, derived from official statements and known file sizes, not from full downloads.
- Streaming throughput (events/sec) is inferred from refresh cadence and fleet counts, not measured.
- Not covered in depth: rail freight systems (Europe/Asia), toll/ETC systems, ride-hailing partner APIs, national ITS archives outside the US/EU, and Vietnam specifics (see vietnam-transportation-data.md).
- Prices and free tiers change frequently; re-verify each at signup.