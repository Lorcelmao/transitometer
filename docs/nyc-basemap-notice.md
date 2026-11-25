# NYC Borough Boundaries Basemap Notice

The interactive NYC Stop map (`/diagnostics/map/`) renders land, water, and borough context from a
self-hosted, simplified GeoJSON derived from **New York City Department of City Planning (NYC DCP)
Borough Boundaries (Clipped to Shoreline)** (`nybb`, NYC Open Data dataset `gthc-hcne`).

## Source, licence, and checksums

| Field | Value |
|---|---|
| Upstream dataset | NYC Department of City Planning — Borough Boundaries (Clipped to Shoreline) (`nybb`, NYC Open Data `gthc-hcne`) |
| Retrieval endpoint | `https://services5.arcgis.com/GfwWNkhOj9bNBqoJ/arcgis/rest/services/NYC_Borough_Boundary/FeatureServer/0/query?where=1%3D1&outFields=BoroCode,BoroName&f=geojson` |
| Licence / terms | NYC Open Data Terms of Use (public civic data; attribution to NYC Department of City Planning) |
| Download date | `2026-11-25` |
| Raw upstream file size | `2,982,467` bytes (5 boroughs, 118 polygons, 99,644 vertices) |
| Raw upstream SHA-256 | `a2eec95024f267de25af06e68fde30004ec05f2a88a983e582d4b3c6eaf7b693` |
| Committed file | `web/public/basemap/nyc-boroughs.geojson` |
| Simplification | Closed-ring Ramer–Douglas–Peucker (`eps = 0.0004°`, approx. 40 m), drop islets under `2e-5 sq deg`, coordinates rounded to 5 decimal places, sorted by `boro_code` (`1` Manhattan, `2` Bronx, `3` Brooklyn, `4` Queens, `5` Staten Island) |
| Committed file size | `56,092` bytes raw (`13,504` bytes gzip; 22 polygons, 2,950 vertices) |
| Committed file SHA-256 | `e79e5c1277d08ba99c8a220d50b71c1c25d2ff667e68c8d1368041c89c62e33d` |

## Companion MTA route geometry

Bus streets and subway lines in `web/public/basemap/` are generated locally from the pinned MTA
static GTFS timetables by `python tasks.py web-basemap`:

- `web/public/basemap/nyc.json` — combined merged bus streets and subway lines (`transitometer.basemap/1`).
- `web/public/basemap/nyc-subway.json` — subway lines only (`transitometer.basemap-subway/1`), loaded with `nyc-boroughs.geojson` for the initial map frame.
- `web/public/basemap/nyc-streets.json` — merged bus street network (`transitometer.basemap-streets/1`), loaded lazily only when zoomed into street corridors.

No third-party map tiles or runtime external requests are used.
