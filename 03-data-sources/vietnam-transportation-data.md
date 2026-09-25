# Vietnam Transportation Data Availability — Verification Report

**Course:** CO5173 Data Engineering (HCMUT) · **Domain:** Transportation · **Scope:** Feasibility of a Vietnam-focused (HCMC/Hanoi) data-engineering project vs. international datasets
**Date:** 2026-09-23 · **Method:** Primary-source probing (HTTP fetch of portals/APIs, GTFS catalog inspection) + web search. No paywalled or credentialed sources were accessed.

## Legend
- **[VERIFIED]** — Confirmed by direct primary-source inspection (URL + observed response) or authoritative owner documentation.
- **[UNVERIFIED]** — Reported by secondary sources; not confirmed against a primary source this session.
- **[ASSUMPTION]** — Analyst inference; not independently confirmed.

## Verdict (read this first)
Vietnam-specific **open** transport data is **THIN and mostly static/aggregate**. There is effectively **no official GTFS for HCMC**, **no GTFS-Realtime anywhere in Vietnam**, no open streaming API from any Vietnamese transport authority, and no usable national open-data portal for transport. The country has **exactly one genuinely usable, licensed, downloadable transit dataset** (Hanoi GTFS from the World Bank) plus good *geospatial* and *congestion-index* coverage (OpenStreetMap, TomTom). Anything with real streaming volume must come from **non-Vietnamese feeds** or from **unofficial scraping** of HCMC systems (legal risk).

**Recommendation:** a Vietnam-focused project is feasible only as a **batch/static** pipeline (Hanoi GTFS + OSM + TomTom CSV + aggregate statistics). For a project requiring genuine high-volume **streaming**, use an **international GTFS/GTFS-RT corpus** (Mobility Database) as the core, and use Vietnam as an enrichment/case-study layer. See Ranking at the end.

---

## 1. Ho Chi Minh City / Vietnam public transport

### 1.1 HCMC bus system (MCPT)
- **Operator/authority:** Trung tâm Quản lý Giao thông công cộng TP.HCM (MCPT — HCMC Management Centre of Public Transport), under Sở Xây dựng TPHCM. ~150–158 routes. **[VERIFIED]** (Wikipedia VI entry; hcmc gov portals)
- **Official GTFS feed:** **NONE FOUND.** No GTFS download, no Google Transit feed, no published schedule export on any HCMC government site. **[VERIFIED negatively]** — absence confirmed across HCMC open-data portal, transport-data.org, OD Mekong, and Transitland/Mobility Database catalogs.
- **Open data portal:** `https://opendata.hochiminhcity.gov.vn` — a live Drupal/DKAN portal run by **Trung tâm Chuyển đổi số TPHCM** (HCMC Digital Transformation Center). **[VERIFIED exists]** — but its topic taxonomy is *investment, health, construction, society, culture, justice, economy, agriculture, science, education, labour, finance* — **transport is NOT a topic category**. ~105 datasets, almost all **PDF/XLSX**; downloads gated by CAPTCHA. No GTFS, no bus schedule dataset observed. **[VERIFIED]**
- **Bus apps (proprietary, not open):** BusMap (Phenikaa MaaS), Go!Bus HCMC, and MCPT's own app — real-time bus GPS exists internally but is **not exposed** as open data/API. **[VERIFIED — apps exist; ASSUMPTION on no public API]**
- **Research workaround:** a Vingroup-funded project reconstructed observed GTFS from BusMap vehicle-GPS data (`github.com/LinhLTP/vinf_bus_time_tables`) — evidence that the *only* path to HCMC bus GTFS is scraping/reconstruction, not an official feed. **[VERIFIED]**

### 1.2 HCMC Metro — Line 1 (Ben Thanh–Suoi Tien)
- **Status:** opened commercially **22 Dec 2024**; officially inaugurated 9 Mar 2025. 19.7 km, 14 stations (3 underground, 11 elevated). **[VERIFIED]** (JICA; VietnamPlus; SGGP)
- **Roles:** Investor/authority = **MAUR** (Management Authority for Urban Railways). Operator = **HCMC Urban Railway No. 1 Company Limited (HURC1)**. Consumer app = **"HCMC Metro HURC"** (QR ticketing, citizen-ID gates). **[VERIFIED]**
- **Open data / GTFS / GTFS-RT:** **NONE FOUND.** No published feed, no real-time API, no open data on MAUR/HURC sites. **[VERIFIED negatively]**

### 1.3 Hanoi bus & Hanoi Metro
- **Hanoi bus GTFS:** **EXISTS** — World Bank Data Catalog dataset **0038236**, "Hanoi, Vietnam — General Transit Feed Specification (GTFS)", containing **AM / MD (midday) / PM** GTFS sets. **License: Creative Commons Attribution 4.0 (CC-BY 4.0).** **[VERIFIED]** — download tested: ZIP ~1.55 MB, `application/zip`, contains `stops.txt` (PK magic confirmed). Mirrored on transport-data.org as `gtfs-hanoi` (+ Afternoon/Morning). Dataset dates ~2020–2023; provenance is World Bank/TUMI (likely reconstructed, **not** an official Hanoi-operator feed). **[VERIFIED download; ASSUMPTION on provenance]**
- **Hanoi bus map / static geo datasets:** `Hanoi-Bus-Map`, `Hanoi_Bus_Gtk`, `Railway Station Of Vietnam` (GPKG/CSV/GeoJSON), `Road And Railway Network Of Vietnam` (GPKG/CSV/GeoJSON/ZIP). **[VERIFIED]** (TDC/OD Mekong)
- **Hanoi Metro:** Line 2A (Cat Linh–Ha Dong, 2021) and Line 3 elevated (Nhon–Cau Giay, 2024) operational. **No open data/GTFS-RT found.** **[VERIFIED negatively]**

### 1.4 National open-data portals
| Portal | Status | Transport content |
|---|---|---|
| **data.gov.vn** (National Open Data Portal, CKAN) | **[VERIFIED problematic]** — DNS did **not resolve** during testing; **SSL cert expired 24 Jun 2025**; hosted on VNPT. World Bank's 2025 assessment still cites it as the national portal. Effectively **low/unreliable usability**. | None usable found |
| **opendata.hochiminhcity.gov.vn** | VERIFIED live | No transport category |
| **opendata.danang.gov.vn** | VERIFIED live (has API/Zalo) | Not transport-focused |
| Provincial CKAN portals (Long An, Binh Dinh, Hue, Hai Phong, Can Tho…) | VERIFIED listed | No transit feeds |
| **transport-data.org / hub.tumidata.org** (TUMI CKAN) | VERIFIED live | **Best aggregator**: ~35 Vietnam-related entries (GTFS Hanoi, road/rail network, railway stations, traffic-API pointers) |
| **OD Mekong** (vietnam.opendevelopmentmekong.net) | VERIFIED live | Road & railway network, railway stations, yearbooks |

### 1.5 Ministry of Transport / DRVN / Vietnam Register
- **MoT / Directorate for Roads of Vietnam (DRVN):** publishes **web/aggregate statistics only**; no downloadable datasets or APIs. **[VERIFIED — no open datasets observed]**
- **Vietnam Register (Cục Đăng kiểm):** publishes **aggregate inspection statistics** via news (e.g., 2024: ~5.4M inspection turns, 15.8% initial-fail). **No open datasets.** Vehicle/plate data is federated into the national population DB (VNeID) — **not accessible**, legally restricted. **[VERIFIED]**

---

## 2. Vietnam traffic & mobility

- **HCMC traffic portal `giaothong.hochiminhcity.gov.vn`:** live "traffic status" map + **traffic cameras**, and a public map/GIS. **[VERIFIED live]**. Under the hood it uses **SignalR** (`communicationHub`), legacy **AjaxPro**, and a **shared GIS API** (`gisapi.tphcm.gov.vn`) with an **API key embedded in client JS** (`99a55f41-…`). There is **no documented public API**; consumption requires reverse-engineering. **[VERIFIED — undocumented]**
- **TomTom Traffic Index:** public **HCMC & Hanoi congestion dashboards** (2025: HCMC 46.9%, Hanoi 49.2% avg congestion; rush-hour speeds ~15 km/h). TomTom also advertises **Area Analytics "hourly CSV for every hour of the day, free"** per city. **[VERIFIED pages; CSV availability stated by vendor — page returned 503 during test, so treat as UNVERIFIED until downloaded]**
- **HERE / TomTom traffic APIs:** commercial, paid, credentialed. **[VERIFIED]**
- **Third-party:** Kaggle "Traffic Flow Data in Ho Chi Minh City, Vietnam" (community-uploaded) — scouted by TUMI; **UNVERIFIED** quality/provenance.
- **Ride-hailing (Grab / Be / Xanh SM):**
  - **Grab** exposes **partner APIs** (developer.grab.com) — OAuth2 with **partner-issued credentials**; no open consumer data. **[VERIFIED]**
  - **Grab-Posisi** — a real *research* GPS-trajectory dataset (84K trajectories, 80M+ pings, ~2 GB Parquet, Apr 2019, **Singapore**, request via `grab.posisi@grabtaxi.com`). **Not Vietnam**, request-gated. **[VERIFIED]**
  - **Be / Xanh SM:** **no** open data or public API. **[VERIFIED negatively]**
- **Road accident statistics:** National Traffic Safety Committee / National Statistics Office publish **aggregate** figures via press/news (e.g., 10M-2025: 15,251 crashes, 8,515 deaths). WHO / Johns Hopkins BIGRS provide modeled/city-level estimates (Hanoi fatalities 2015–2024). **No crash microdata.** **[VERIFIED aggregate only]**
- **Expressway / toll (VETC, ePass):** proprietary ETC platforms; VETC ~4.3M app users, ePass ~3.2M subscribers / 1B+ passages. **No open data, no public API.** **[VERIFIED]**
- **OpenStreetMap:** full Vietnam road network via **Geofabrik** (`geofabrik.de/asia/vietnam.html`), **ODbL**. Real scale, genuinely usable. **[VERIFIED — canonical source]**

---

## 3. Aviation & maritime (aggregate only)

- **Aviation — CAAV / ACV:** ACV operates 22 airports; publishes **annual reports (PDF)** and monthly aggregates (2025: 121M passengers, 1.756M tonnes cargo, 745k movements). CAAV releases aggregate passenger/cargo via news. **No datasets/API/microdata.** ACV is a public company (UPCoM: ACV) → financial statements only. **[VERIFIED aggregate]**
- **Maritime — Vinamarine / Vietnam Seaports Association / Saigon Port / CMIT:** aggregate throughput via news and port sites (Cai Mep–Thi Vai ≈152M tonnes / 34% of national containers in 2024; CMIT 2M TEU in 11 months 2025). NSO publishes port rankings. **No API/datasets.** **[VERIFIED aggregate]**
- **Statistical Yearbook (NSO/GSO) 2024:** downloadable **PDF** with a Transport chapter (annual, national/provincial aggregates). Best single official statistical source. **[VERIFIED PDF]**

---

## 4. Practical assessment matrix

| Source | Exists? | Downloadable | License | Format | Update freq | API | Cost/Auth | Fit |
|---|---|---|---|---|---|---|---|---|
| **Hanoi GTFS (World Bank 0038236)** | Yes | **Yes (tested)** | **CC-BY 4.0** | GTFS (ZIP) | One-off (2020–2023) | No | Free | **Good (static)** |
| OSM Vietnam (Geofabrik) | Yes | Yes | ODbL | PBF/SHP | Daily | No (bulk) | Free | **Good (geo, big)** |
| TomTom Traffic Index + Area Analytics CSV | Yes | Stated free | Vendor ToS | CSV/web | Hourly/annual | Paid API | Free CSV | **Good (congestion)** |
| HCMC open-data portal | Yes | CAPTCHA | Unclear | PDF/XLSX | Ad-hoc | No | Free | Poor (no transport) |
| HCMC traffic portal (live cameras/status) | Yes | No | ToS-restricted | HTML/SignalR | Live | Hidden | Free (unofficial) | **Risky** |
| HCMC Metro (HURC1/MAUR) | Yes (service) | No | — | — | — | No | — | None |
| HCMC bus GTFS | **No** | No | — | — | — | No | — | None official |
| Hanoi bus map / rail network (OD Mekong) | Yes | Yes | Unspecified | GPKG/CSV/GeoJSON | Static | No | Free | Fair |
| data.gov.vn (national) | Nominal | **Broken** | — | — | — | No | Free | Poor |
| NSO Statistical Yearbook | Yes | Yes | Public | PDF | Annual | No | Free | Poor (aggregate) |
| CAAV / ACV / ports | Yes | Yes (PDF) | Public | PDF | Annual | No | Free | Poor (aggregate) |
| Vietnam Register / DRVN | Yes | Mostly no | — | PDF/web | Ad-hoc | No | Free | Poor |
| Grab / Be / Xanh SM | Apps yes | **No** | Proprietary | — | — | Partner-only | Contract | None |
| VETC / ePass | Yes | No | Proprietary | — | — | No | — | None |
| Mobility Database (global) | Yes | Yes | Mixed (open) | GTFS/GTFS-RT | Continuous | Yes | Free | **Best for streaming** |

**Volumetric reality check:** the *only* Vietnam transit dataset with genuine structure and a clean license (Hanoi GTFS) is a **~1.5 MB static ZIP**. Everything else Vietnam is either geospatial (OSM — large but not "transport operations" data), congestion indices (TomTom — derived), or **aggregate PDF statistics**. There is **no Vietnamese source of transit telemetry, no GTFS-RT, no event stream**. "Streaming" from Vietnam therefore means *unofficial scraping*, not an API.

---

## 5. Legal / ethical risk for scraping Vietnamese systems
- **HCMC traffic portal / HCMC open-data portal:** no published public API. Reusing the **embedded GIS API key** or reverse-engineering the **SignalR hub** is **unauthorized use** and likely breaches portal terms. **[VERIFIED mechanism; ASSUMPTION on ToS wording]**
- **Legal framework:** Vietnam's **Decree 147/2024/ND-CP** (internet/online information management, effective 25 Dec 2024) and site "Điều khoản sử dụng" (Terms of Use) generally restrict automated scraping. Data linked to the **national population database (VNeID)** — e.g., vehicle/plate/driver records — is **off-limits** and carries criminal exposure.
- **Ethical:** government portals are often under-resourced (single-server ASP.NET apps); aggressive scraping risks degradation. Prefer bulk/official files, cache aggressively, respect `robots.txt` and rate limits, and never bypass CAPTCHAs.

---

## 6. Ranked recommendation

**Option A — Vietnam-focused, batch-only (feasible, lower ceiling).**
Core: Hanoi GTFS (CC-BY 4.0) + OSM Vietnam (ODbL) + TomTom congestion CSVs + NSO Yearbook aggregates. Demonstrates ingestion, modeling, spatial joins, and batch pipelines. **Weakness:** no true streaming/high-volume telemetry; ~1.5 MB transit core is small. Use if the rubric rewards *domain localisation* over volume.

**Option B — International streaming core + Vietnam case study (RECOMMENDED).**
Core: **Mobility Database** (6,000+ GTFS + GTFS-RT feeds, 99 countries) for real high-volume **streaming** (GTFS-Realtime vehicle positions/trip updates). Vietnam layer: Hanoi GTFS + OSM Vietnam + TomTom to localise the analysis. **Best of both: real streaming scale + Vietnamese relevance.** **[VERIFIED — Mobility DB catalog confirmed, e.g. 3,569+ feed files inspected]**

**Option C — Pure global dataset (safest technical fit).**
Pick 1–3 mature GTFS-RT feeds (e.g., US/EU). Maximises volume, tooling maturity, and reproducibility; sacrifices Vietnam relevance.

**Not recommended:** any plan assuming an official HCMC bus GTFS, HCMC/Hanoi metro real-time data, data.gov.vn, ride-hailing open data, or toll/aviation/maritime datasets.

---

## 7. Unresolved questions
1. Is `data.gov.vn` **permanently retired**, migrated, or just down (SSL expired, DNS unresolved)? A 2026 national-data-strategy push suggests migration is underway. **Re-verify before citing.**
2. TomTom **Area Analytics hourly CSV** for HCMC/Hanoi — download page returned 503 during testing; confirm actual availability/licence terms. **UNVERIFIED.**
3. Exact **licence/provenance** of the World Bank Hanoi GTFS (reconstructed vs. official) and whether a newer (post-2023) version exists.
4. Whether **MAUR/HURC1** or **MCPT** will publish GTFS/GTFS-RT under Vietnam's 2026–2030 national data strategy. Currently: no signal.
5. HCMC open-data portal download semantics (CAPTCHA + auth) — whether any transport datasets exist behind the general listing.
