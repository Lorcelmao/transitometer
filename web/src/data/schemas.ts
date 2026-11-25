/**
 * The contract with the Python export (src/transitometer/serve/web_export.py).
 *
 * Every JSON file in public/data is validated against these schemas when the site is built
 * (and when a stop file is fetched), so a missing field, a renamed column or a schema version
 * change fails the build instead of rendering a wrong number. The site never computes a metric:
 * values and display strings arrive ready from the shared Python views.
 */
import * as z from "zod/mini";

import { MAP_COLUMNS, type MapStopRow } from "@/data/map-columns";

export { MAP_COLUMNS, type MapStopRow };

export const SCHEMA = "transitometer.web/1";

const num = z.number();
const maybeNum = z.nullable(z.number());

export const badge = z.object({
  label: z.string(),
  tone: z.enum(["pass", "fail", "attention", "neutral"]),
});
export type Badge = z.infer<typeof badge>;

export const figure = z.object({
  key: z.string(),
  label: z.string(),
  value: z.union([z.number(), z.null()]),
  display: z.string(),
  help: z.nullable(z.string()),
  basis: z.optional(z.nullable(z.string())),
  badge: z.optional(z.nullable(badge)),
});
export type Figure = z.infer<typeof figure>;

const caveat = z.nullable(z.object({ value: maybeNum, display: z.string(), text: z.string() }));

/** Every exported file: schema version, view name, filters, provenance, then the view's data. */
export const envelope = z.object({
  schema: z.literal(SCHEMA),
  view: z.string(),
  filters: z.record(z.string(), z.string()),
  source: z.object({
    snapshot_commit: z.string(),
    validated_on: z.string(),
    tables: z.array(z.string()),
  }),
  data: z.unknown(),
});
export type Source = z.infer<typeof envelope>["source"];

/** Validate a file's envelope, then its data against the view's schema; throw with the reason. */
export function parseView<T extends z.ZodMiniType>(
  name: string,
  body: unknown,
  schema: T,
): { data: z.infer<T>; source: Source } {
  const outer = envelope.safeParse(body);
  if (!outer.success) throw new Error(`${name}: not a ${SCHEMA} file: ${issues(outer.error)}`);
  const inner = schema.safeParse(outer.data.data);
  if (!inner.success) throw new Error(`${name} does not match its schema: ${issues(inner.error)}`);
  return { data: inner.data as z.infer<T>, source: outer.data.source };
}

function issues(error: { issues: { path: PropertyKey[]; message: string }[] }): string {
  return error.issues
    .slice(0, 5)
    .map((i) => `${i.path.map(String).join(".") || "(root)"}: ${i.message}`)
    .join("; ");
}

export const meta = z.object({
  schema: z.literal(SCHEMA),
  snapshot: z.object({
    validated_commit: z.string(),
    validated_on: z.string(),
    validation: z.object({
      ok: z.boolean(),
      silver: z.object({ passed: num, total: num }),
      gold: z.object({ passed: num, total: num }),
    }),
    tables: z.record(
      z.string(),
      z.object({ rows: num, bytes: num, sha256: z.string(), validated: z.boolean() }),
    ),
    evidence: z.record(z.string(), z.string()),
  }),
  modes: z.array(z.object({ key: z.string(), label: z.string(), short: z.string() })),
  days: z.array(z.object({ key: z.string(), label: z.string() })),
  pages: z.record(
    z.string(),
    z.object({ streamlit: z.string(), route: z.string(), tables: z.array(z.string()) }),
  ),
  repository: z.string(),
});
export type Meta = z.infer<typeof meta>;

export const overview = z.object({
  views: z.record(
    z.string(),
    z.object({
      grp: z.string(),
      group_label: z.string(),
      day: z.string(),
      day_label: z.string(),
      takeaway: z.string(),
      feed_checks: z.nullable(z.object({ passed: num, total: num, failed: z.array(z.string()) })),
      figures: z.array(figure),
      hours: z.array(
        z.object({
          service_hour: num,
          hour_label: z.string(),
          events: num,
          on_time_share: maybeNum,
          display: z.string(),
          sufficient: z.boolean(),
        }),
      ),
      hourly_min_events: num,
      caveat,
    }),
  ),
  findings: z.array(
    z.object({
      key: z.string(),
      kicker: z.string(),
      value: z.string(),
      badge,
      headline: z.string(),
      detail: z.string(),
      stats: z.optional(z.looseObject({})),
      page: z.string(),
    }),
  ),
  pipeline: z.object({
    messages: z.nullable(z.string()),
    archive_rows: z.nullable(z.string()),
    stop_events: z.string(),
    silver: z.nullable(z.string()),
    gold: z.nullable(z.string()),
    gold_seconds: z.nullable(z.string()),
    tests: z.nullable(z.string()),
  }),
  hero: z.object({
    columns: z.array(z.string()).check(z.refine((c) => c.join() === "lat,lon,events,on_time_share,sufficient", "hero columns changed")),
    cells: z.array(z.tuple([num, num, num, maybeNum, z.boolean()])),
    stops: num,
    caption: z.string(),
  }),
  trust: z.object({
    integrity: z.object({
      available: z.boolean(),
      ok: z.boolean(),
      archive_rows: maybeNum,
      archive_rows_display: z.string(),
      status: z.string(),
    }),
    parity: z.object({
      available: z.boolean(),
      ok: z.boolean(),
      passed: num,
      total: num,
      display: z.string(),
    }),
    badge,
  }),
});
export type Overview = z.infer<typeof overview>;

const routeShare = z.object({
  route_id: z.string(),
  events: num,
  on_time_share: num,
  late_share: num,
});
export const onTime = z.object({
  day: z.string(),
  day_label: z.string(),
  takeaway: z.nullable(z.string()),
  routes: z.array(routeShare),
  ranking: z.array(routeShare),
  cells: z.array(
    z.object({
      route_id: z.string(),
      service_hour: num,
      hour_label: z.string(),
      hour_short: z.string(),
      events: num,
      on_time_share: maybeNum,
      late_share: maybeNum,
      median_delay_s: maybeNum,
      scored: z.boolean(),
    }),
  ),
  min_events: num,
  definitions: z.string(),
});
export type OnTime = z.infer<typeof onTime>;

export const headways = z.object({
  day: z.string(),
  day_label: z.string(),
  takeaway: z.nullable(z.string()),
  summary: z.nullable(z.looseObject({ headways: num })),
  figures: z.array(figure),
  routes: z.array(
    z.object({
      route_id: z.string(),
      headways: num,
      bunched: num,
      gaps: num,
      bunched_share: num,
      regular_share: num,
    }),
  ),
  cells: z.array(
    z.object({
      route_id: z.string(),
      service_hour: num,
      hour_label: z.string(),
      headways: num,
      regular_share: maybeNum,
      bunched: num,
      gaps: num,
    }),
  ),
  definitions: z.string(),
});
export type Headways = z.infer<typeof headways>;

export const missingTrips = z.object({
  day: z.string(),
  day_label: z.string(),
  takeaway: z.nullable(z.string()),
  summary: z.nullable(z.looseObject({ scheduled: num })),
  figures: z.array(figure),
  outcomes: z.array(
    z.object({
      key: z.string(),
      outcome: z.string(),
      trips: num,
      order: num,
      not_delivered: z.boolean(),
    }),
  ),
  caveat,
  routes: z.array(
    z.object({
      route_id: z.string(),
      scheduled: num,
      delivered: num,
      partial: num,
      missing: num,
      not_run: num,
      unknown: num,
      not_delivered_share: num,
    }),
  ),
  min_trips: num,
  definitions: z.string(),
});
export type MissingTrips = z.infer<typeof missingTrips>;

export const delay = z.object({
  day: z.string(),
  day_label: z.string(),
  takeaway: z.nullable(z.string()),
  summary: z.nullable(z.looseObject({ trip_vehicles: num })),
  figures: z.array(figure),
  caption: z.nullable(z.string()),
  definitions: z.string(),
});
export type Delay = z.infer<typeof delay>;

export const segments = z.object({
  segments: z.array(
    z.object({
      route_id: z.string(),
      direction_id: maybeNum,
      service_hour: num,
      hour_label: z.string(),
      from_stop: z.string(),
      to_stop: z.string(),
      from_name: z.string(),
      to_name: z.string(),
      segments: num,
      sched_travel_s: num,
      p50_travel_s: num,
      p90_travel_s: num,
      median_excess_s: num,
      segment: z.string(),
    }),
  ),
  min_segments: num,
  caption: z.string(),
});
export type Segments = z.infer<typeof segments>;

const scorecardRoute = z.object({
  route_id: z.string(),
  events: num,
  trips: num,
  on_time_share: num,
  ci_low: maybeNum,
  ci_high: maybeNum,
  sufficient: z.boolean(),
  rank: maybeNum,
  rank_low: maybeNum,
  rank_high: maybeNum,
  rank_interval: z.string(),
});
export type ScorecardRoute = z.infer<typeof scorecardRoute>;
export const scorecards = z.object({
  ranked: z.array(scorecardRoute),
  unranked: z.array(scorecardRoute),
  least: z.array(scorecardRoute),
  most: z.array(scorecardRoute),
  caption: z.string(),
  definitions: z.string(),
});
export type Scorecards = z.infer<typeof scorecards>;

export const stopIndex = z.object({
  routes: z.array(z.object({ route_id: z.string(), file: z.string(), stops: num })),
  min_cell_events: num,
  definitions: z.string(),
});
export type StopIndex = z.infer<typeof stopIndex>;

export const HOUR_COLUMNS = [
  "service_hour",
  "hour_label",
  "hour_short",
  "events",
  "on_time",
  "on_time_share",
  "ci_low",
  "ci_high",
  "late",
  "early",
  "p50_delay_s",
  "p90_delay_s",
  "sufficient",
] as const;
export const stopRoute = z.object({
  hour_columns: z
    .array(z.string())
    .check(z.refine((columns) => columns.join() === HOUR_COLUMNS.join(), "hour columns changed")),
  figures: z.array(z.object({ key: z.string(), label: z.string(), help: z.nullable(z.string()) })),
  stops: z.array(
    z.object({
      direction_id: maybeNum,
      stop_id: z.string(),
      stop_name: z.nullable(z.string()),
      label: z.string(),
      values: z.record(z.string(), maybeNum),
      display: z.record(z.string(), z.string()),
      hours: z.array(
        z.tuple([
          num,
          z.string(),
          z.string(),
          num,
          num,
          maybeNum,
          maybeNum,
          maybeNum,
          num,
          num,
          maybeNum,
          maybeNum,
          z.boolean(),
        ]),
      ),
    }),
  ),
});
export type StopRoute = z.infer<typeof stopRoute>;

const mapStopRow = z.tuple([
  z.string(),
  z.string(),
  num,
  num,
  num,
  num,
  z.string(),
  z.boolean(),
  z.string(),
  maybeNum,
  num,
  z.nullable(z.string()),
]);

export const stopMap = z.object({
  columns: z
    .array(z.string())
    .check(z.refine((columns) => columns.join() === MAP_COLUMNS.join(), "map columns changed")),
  stops: z.array(mapStopRow),
  worst: z.array(z.string()),
  sufficient: num,
  min_events: num,
  summary: z.string(),
  definitions: z.string(),
});
export type StopMap = z.infer<typeof stopMap>;

/** Pre-aggregated 670 m grid cell: [lon, lat, events, shareOrNull, stopCount, suffCount, topStop, topRoute, band, deltaPts]. */
export const mapGridCell = z.tuple([
  num,
  num,
  num,
  maybeNum,
  num,
  num,
  z.string(),
  z.string(),
  num,
  z.nullable(z.string()),
]);
export type MapGridCell = z.infer<typeof mapGridCell>;

export const mapBandSpec = z.object({
  id: num,
  label: z.string(),
  range: z.string(),
  color: z.string(),
  max: maybeNum,
});

export const mapThinBand = z.object({
  id: z.literal("thin"),
  label: z.string(),
  color: z.string(),
});

export const mapTileSpec = z.object({
  min_lon: num,
  max_lon: num,
  min_lat: num,
  max_lat: num,
  n: num,
  tiles: z.array(z.string()),
});
export type MapTileSpec = z.infer<typeof mapTileSpec>;

/** Lightweight Stop map payload: summary stats, equal-weighted stop median, diverging bands, top-50 table rows, 670 m grid. */
export const stopMapGrid = z.object({
  mode: z.string(),
  columns: z
    .array(z.string())
    .check(z.refine((columns) => columns.join() === MAP_COLUMNS.join(), "map columns changed")),
  total: num,
  sufficient: num,
  thin: num,
  min_events: num,
  stop_median_share: maybeNum,
  stop_median_display: z.string(),
  bands: z.array(mapBandSpec),
  thin_band: mapThinBand,
  band_counts: z.array(num),
  summary: z.string(),
  definitions: z.string(),
  worst_rows: z.array(mapStopRow),
  grid_cells: z.array(mapGridCell),
  stops: z.array(mapStopRow),
  tile_spec: z.nullable(mapTileSpec),
});
export type StopMapGrid = z.infer<typeof stopMapGrid>;

export const stopMapTile = z.object({
  columns: z
    .array(z.string())
    .check(z.refine((columns) => columns.join() === MAP_COLUMNS.join(), "map columns changed")),
  stops: z.array(mapStopRow),
});
export type StopMapTile = z.infer<typeof stopMapTile>;

/**
 * The stop map's background (`python tasks.py web-basemap`, public/basemap/nyc*.json) plus
 * simplified NYC DCP borough boundaries (`public/basemap/nyc-boroughs.geojson`).
 */
const polyline = z.array(z.tuple([num, num]));
export const basemap = z.object({
  schema: z.literal("transitometer.basemap/1"),
  source: z.string(),
  streets: z.array(polyline),
  subway: z.array(z.object({ color: z.string(), lines: z.array(polyline) })),
});
export type Basemap = z.infer<typeof basemap>;

export const basemapSubway = z.object({
  schema: z.literal("transitometer.basemap-subway/1"),
  source: z.string(),
  subway: z.array(z.object({ color: z.string(), lines: z.array(polyline) })),
});
export type BasemapSubway = z.infer<typeof basemapSubway>;

export const basemapStreets = z.object({
  schema: z.literal("transitometer.basemap-streets/1"),
  source: z.string(),
  streets: z.array(polyline),
});
export type BasemapStreets = z.infer<typeof basemapStreets>;

export const nycBoroughs = z.object({
  type: z.literal("FeatureCollection"),
  features: z.array(
    z.object({
      type: z.literal("Feature"),
      properties: z.object({
        boro_code: num,
        name: z.string(),
      }),
      geometry: z.looseObject({ type: z.string() }),
    }),
  ),
});
export type NycBoroughs = z.infer<typeof nycBoroughs>;

export const earlyWarning = z.object({
  held_out_day: z.string(),
  held_out_label: z.string(),
  development_day: z.string(),
  min_precision: num,
  min_precision_display: z.string(),
  verdicts: z.array(
    z.object({
      outcome: z.string(),
      title: z.string(),
      available: z.boolean(),
      passed: z.optional(z.boolean()),
      verdict: z.optional(z.string()),
      f1: z.optional(num),
      f1_display: z.optional(z.string()),
      baseline_f1: z.optional(num),
      baseline_f1_display: z.optional(z.string()),
      precision_display: z.optional(z.string()),
      recall_display: z.optional(z.string()),
      caption: z.optional(z.string()),
    }),
  ),
  comparison: z.array(
    z.object({
      service_date: z.string(),
      outcome: z.string(),
      method: z.string(),
      Method: z.string(),
      day: z.string(),
      precision: num,
      recall: num,
      f1: num,
      decisions: num,
    }),
  ),
  // What the rules would have shown a dispatcher on the held-out day (views.warning_list).
  dispatcher: z.object({
    available: z.boolean(),
    day_label: z.optional(z.string()),
    min_decisions: z.optional(num),
    routes: z.optional(
      z.array(
        z.object({
          route_id: z.string(),
          decisions: num,
          warnings: num,
          bar: num,
          late_display: z.string(),
          bunched_display: z.string(),
        }),
      ),
    ),
    hours: z.optional(
      z.array(
        z.object({
          service_hour: num,
          label: z.string(),
          hour_label: z.string(),
          decisions: num,
          warnings: num,
          bar: num,
          late_display: z.string(),
          bunched_display: z.string(),
        }),
      ),
    ),
    examples: z.optional(
      z.array(
        z.object({
          kind: z.string(),
          route_id: z.string(),
          static_trip_id: z.string(),
          stop: z.string(),
          time: z.string(),
          delay_display: z.string(),
          projected_display: z.string(),
          outcome: z.string(),
        }),
      ),
    ),
    routes_caption: z.optional(z.string()),
    hours_caption: z.optional(z.string()),
    examples_caption: z.optional(z.string()),
  }),
  definitions: z.string(),
});
export type EarlyWarning = z.infer<typeof earlyWarning>;

export const feedHealth = z.object({
  views: z.record(
    z.string(),
    z.object({
      day: z.string(),
      day_label: z.string(),
      feeds: z.array(
        z.object({
          feed: z.string(),
          label: z.string(),
          score: num,
          display: z.string(),
          help: z.string(),
          passed: num,
          total: num,
          failed_count: num,
          badge,
          status_badge: badge,
          failed: z.array(z.string()),
          checks: z.array(
            z.object({
              metric: z.string(),
              passed: z.boolean(),
              result: z.string(),
              check: z.string(),
              value: maybeNum,
              threshold: num,
              measured: z.string(),
              threshold_display: z.string(),
              description: z.string(),
            }),
          ),
        }),
      ),
      definitions: z.string(),
    }),
  ),
});
export type FeedHealth = z.infer<typeof feedHealth>;

export const validation = z.object({
  datasets: z.array(z.object({ Dataset: z.string(), Content: z.string(), Source: z.string() })),
  integrity: z.looseObject({ available: z.boolean(), files: z.array(z.string()) }),
  integrity_table: z.array(z.record(z.string(), z.string())),
  parity: z.object({
    available: z.boolean(),
    ok: z.boolean(),
    layers: z.array(
      z.looseObject({ layer: z.string(), passed: num, total: num, file: z.string() }),
    ),
  }),
  parity_tables: z.array(
    z.object({ Layer: z.string(), Table: z.string(), Result: z.string(), "Rows compared": maybeNum }),
  ),
  policy: z.string(),
  tests: z.looseObject({
      available: z.boolean(),
      file: z.string(),
      total: z.optional(num),
      passed: z.optional(num),
      failed: z.optional(num),
      skipped: z.optional(num),
      ran: z.optional(num),
  }),
});
export type Validation = z.infer<typeof validation>;

const hcmcWard = z.object({
  ward_id: z.string(),
  osm_rel_id: num,
  ward_name: z.string(),
  name_en: z.string(),
  admin_level: z.string(),
  in_core_hcmc: z.boolean(),
  area_km2: num,
  covered_any_km2: num,
  coverage_any_400m_share: num,
  covered_freq_conservative_km2: num,
  coverage_freq_conservative_share: num,
  covered_freq_midpoint_km2: num,
  coverage_freq_midpoint_share: num,
  active_stops: num,
  frequent_stops_conservative: num,
  frequent_stops_midpoint: num,
  stops_per_km2: num,
  distinct_routes: num,
  coverage_any_display: z.string(),
  coverage_freq_cons_display: z.string(),
  coverage_freq_mid_display: z.string(),
  area_display: z.string(),
  stops_per_km2_display: z.string(),
});
export type HcmcWard = z.infer<typeof hcmcWard>;

export const hcmcHandCheck = z.object({
  route_ref: z.string(),
  corridor: z.string(),
  operator: z.string(),
  osm_length_km: num,
  published_length_km: z.string(),
  osm_hours: z.string(),
  published_hours: z.string(),
  osm_headway_min: z.string(),
  published_headway_min: z.string(),
  osm_stops_per_dir: num,
  assessment: z.string(),
});
export type HcmcHandCheck = z.infer<typeof hcmcHandCheck>;

export const hcmcCoverage = z.object({
  available: z.boolean(),
  scope: z.string(),
  scope_label: z.string(),
  scopes: z.array(z.object({ key: z.string(), label: z.string(), short: z.string() })),
  summary: z.nullable(z.looseObject({ wards: num, total_area_km2: num })),
  figures: z.array(figure),
  wards: z.array(hcmcWard),
  bottom_wards: z.array(hcmcWard),
  top_wards: z.array(hcmcWard),
  routes: z.array(
    z.object({
      route_ref: z.string(),
      route_name: z.string(),
      operator: z.string(),
      directions: num,
      avg_stops_per_dir: num,
      avg_length_km: maybeNum,
      in_bbox_length_km: maybeNum,
      length_display: z.string(),
      osm_incomplete: z.boolean(),
      osm_note: z.string(),
      interval_min_min: maybeNum,
      interval_max_min: maybeNum,
      sample_interval: z.nullable(z.string()),
      sample_opening_hours: z.nullable(z.string()),
      is_ptv2_all: z.boolean(),
      has_duration: z.boolean(),
    }),
  ),
  quality: z.array(
    z.object({
      metric: z.string(),
      label: z.string(),
      value: num,
      numerator: num,
      denominator: num,
      threshold: num,
      passed: z.boolean(),
      description: z.string(),
      value_display: z.string(),
      threshold_display: z.string(),
      ratio_display: z.string(),
      result: z.string(),
    }),
  ),
  quality_passed: num,
  quality_total: num,
  hand_checks: z.array(hcmcHandCheck),
  definitions: z.string(),
  provenance: z.object({
    schema: z.string(),
    city: z.string(),
    primary_network: z.string(),
    license: z.string(),
    attribution: z.string(),
    crs: z.string(),
    walk_radius_m: num,
    frequent_buses_per_hour: num,
    retrieved_utc: z.string(),
    bus_sha256: z.string(),
    osm_city_timestamp: z.string(),
    tables: z.array(z.string()),
  }),
});
export type HcmcCoverage = z.infer<typeof hcmcCoverage>;

export const hcmcBasemap = z.object({
  schema: z.literal("transitometer.hcmc-basemap/1"),
  source: z.string(),
  core_frame: z.object({ lon: z.tuple([num, num]), lat: z.tuple([num, num]) }),
  wards: z.object({
    type: z.literal("FeatureCollection"),
    features: z.array(
      z.object({
        type: z.literal("Feature"),
        properties: z.object({
          name: z.string(),
          ward_name: z.string(),
          in_core_hcmc: z.boolean(),
        }),
        geometry: z.looseObject({ type: z.string() }),
      }),
    ),
  }),
  routes: z.array(polyline),
  stops: z.array(z.tuple([num, num, num, z.boolean()])),
});
export type HcmcBasemap = z.infer<typeof hcmcBasemap>;
