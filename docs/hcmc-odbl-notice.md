# OpenStreetMap & ODbL 1.0 Licence Notice (BR11 — Ho Chi Minh City Case Study)

The Ho Chi Minh City static bus network case study (BR11) uses map and transit data from
**OpenStreetMap** (`© OpenStreetMap contributors`), licensed under the
**Open Database License (ODbL) 1.0** (<https://opendatacommons.org/licenses/odbl/1-0/>).

## Produced Work vs Derivative Database

To keep the repository lightweight and unambiguously compliant with ODbL 1.0:

1. **Committed in this repository (`Produced Work` + build scripts):**
   - Transformation and spatial analysis scripts in `src/transitometer/hcmc/` and
     `src/transitometer/serve/hcmc_*.py`.
   - Aggregated ward-level coverage statistics, route summaries, quality-audit tables
     (`showcase/data/hcmc/*.parquet`), and simplified rendering geometry
     (`web/public/basemap/hcmc.json`, `web/public/data/hcmc/*.json`).
   - These outputs are analytical summaries and rendered map visuals (**Produced Works**),
     displayed with clear attribution: `© OpenStreetMap contributors (ODbL 1.0)`.
2. **Generated locally only (`Derivative Database`, not committed to Git):**
   - Raw OpenStreetMap JSON extracts (`<data_root>/landing/hcmc/osm_*.json`, checksummed in
     `data-manifest.json`).
   - Derived frequency-based GTFS archive (`<data_root>/exports/hcmc/gtfs_hcmc.zip` and
     `<data_root>/exports/hcmc/gtfs/*.parquet`).
   - Anyone reproducing these files locally runs `python tasks.py hcmc-fetch` and
     `python tasks.py hcmc-build`. If `gtfs_hcmc.zip` is redistributed publicly, it constitutes a
     **Derivative Database** and must remain licensed under **ODbL 1.0** with share-alike and
     OpenStreetMap attribution preserved.

## Data-scope honesty

- OpenStreetMap is community-maintained open data, not an official municipal transit timetable.
- Only ~1 % of HCMC bus route relations carry a `duration` tag, so derived `stop_times.txt`
  records stop order only without fabricated arrival times.
- Most `interval` tags specify peak/off-peak ranges (e.g. `00:10-00:20`). Coverage metrics report
  both the conservative bound (`interval_max`) and midpoint (`interval_mid`).
- Administrative boundaries reflect Vietnam's post-July-2025 two-tier structure on OSM
  (`relation/1973756`, `admin_level=6` wards/communes). Coverage is reported separately for the
  core HCMC bus-network extent and the full post-merger municipal boundary.
