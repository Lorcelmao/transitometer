/**
 * The contract with the Python export (src/transitometer/serve/web_export.py).
 *
 * Every JSON file in public/data is validated against these schemas when the site is built
 * (and when a stop file is fetched), so a missing field, a renamed column or a schema version
 * change fails the build instead of rendering a wrong number. The site never computes a metric:
 * values and display strings arrive ready from the shared Python views.
 */
import * as z from "zod/mini";

export const SCHEMA = "transitometer.web/1";

const num = z.number();
const maybeNum = z.nullable(z.number());

export const figure = z.object({
  key: z.string(),
  label: z.string(),
  value: z.union([z.number(), z.null()]),
  display: z.string(),
  help: z.nullable(z.string()),
  basis: z.optional(z.nullable(z.string())),
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
      figures: z.array(figure),
      hours: z.array(
        z.object({ service_hour: num, events: num, on_time_share: maybeNum, display: z.string(), sufficient: z.boolean() }),
      ),
      hourly_min_events: num,
      caveat,
    }),
  ),
  findings: z.array(
    z.object({ key: z.string(), kicker: z.string(), value: z.string(), headline: z.string(), detail: z.string(), page: z.string() }),
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
  routes: z.array(routeShare),
  ranking: z.array(routeShare),
  cells: z.array(
    z.object({
      route_id: z.string(),
      service_hour: num,
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
        z.tuple([num, num, num, maybeNum, maybeNum, maybeNum, num, num, maybeNum, maybeNum, z.boolean()]),
      ),
    }),
  ),
});
export type StopRoute = z.infer<typeof stopRoute>;

export const MAP_COLUMNS = [
  "stop_id",
  "label",
  "lat",
  "lon",
  "events",
  "on_time_share",
  "display",
  "sufficient",
  "route_id",
  "direction_id",
] as const;
export const stopMap = z.object({
  columns: z
    .array(z.string())
    .check(z.refine((columns) => columns.join() === MAP_COLUMNS.join(), "map columns changed")),
  stops: z.array(
    z.tuple([
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
    ]),
  ),
  worst: z.array(z.string()),
  sufficient: num,
  min_events: num,
  summary: z.string(),
});
export type StopMap = z.infer<typeof stopMap>;

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
          failed: z.array(z.string()),
          checks: z.array(
            z.object({
              metric: z.string(),
              passed: z.boolean(),
              result: z.string(),
              check: z.string(),
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
  }),
});
export type Validation = z.infer<typeof validation>;
