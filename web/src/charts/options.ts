/**
 * ECharts options for the geometric charts (heatmap, route intervals, hourly intervals, stop map).
 *
 * These map exported fields to marks and nothing else: rows arrive filtered, ordered and flagged
 * by the Python views (which routes, which cells are scored, the interval bounds). No sorting,
 * filtering, threshold or arithmetic on metric values happens here.
 */
import type { EChartsCoreOption } from "echarts/core";

import { axisStyle, COLORS } from "@/charts/theme";
import { count, pct, seconds } from "@/lib/format";

type Tip = { data: unknown };

/** Route x hour heatmap of on-time share; thin cells (not scored) are drawn as outlines. */
export function heatmapOption(
  cells: {
    route_id: string;
    service_hour: number;
    hour_label: string;
    hour_short: string;
    events: number;
    on_time_share: number | null;
    late_share: number | null;
    median_delay_s: number | null;
    scored: boolean;
  }[],
  routes: string[],
  font: string,
): EChartsCoreOption {
  const shortByHour = new Map<number, string>();
  for (const c of cells) shortByHour.set(c.service_hour, c.hour_short);
  const hours = Array.from(shortByHour.keys()).sort((a, b) => a - b);
  const point = (c: (typeof cells)[number]) => ({
    value: [hours.indexOf(c.service_hour), routes.indexOf(c.route_id), c.on_time_share ?? 0],
    cell: c,
  });
  const axis = axisStyle(font);
  return {
    grid: { left: 64, right: 16, top: 48, bottom: 40 },
    tooltip: {
      formatter: ({ data }: Tip) => {
        const { cell } = data as { cell: (typeof cells)[number] };
        return [
          `<b>Route ${cell.route_id}</b>, ${cell.hour_label}`,
          `${count(cell.events)} arrivals${cell.scored ? "" : " (too few to score)"}`,
          `On time ${pct(cell.on_time_share)}, late ${pct(cell.late_share)}`,
          `Median delay ${seconds(cell.median_delay_s)}`,
        ].join("<br/>");
      },
    },
    xAxis: {
      type: "category",
      data: hours.map((h) => shortByHour.get(h) ?? String(h)),
      name: "Scheduled hour of the service day (+1 = after midnight)",
      nameLocation: "middle",
      nameGap: 28,
      ...axis,
      splitArea: { show: false },
    },
    yAxis: { type: "category", data: routes, inverse: true, ...axis },
    visualMap: {
      seriesIndex: 0,
      min: 0,
      max: 1,
      orient: "horizontal",
      top: 0,
      left: "center",
      itemWidth: 10,
      itemHeight: 160,
      calculable: false,
      text: ["100 % on time", "0 %"],
      textStyle: { color: COLORS.muted, fontFamily: font, fontSize: 12 },
      inRange: { color: [...COLORS.sequential] },
    },
    series: [
      {
        type: "heatmap",
        data: cells.filter((c) => c.scored).map(point),
        itemStyle: { borderColor: COLORS.paper, borderWidth: 1.5 },
        emphasis: { itemStyle: { borderColor: COLORS.ink, borderWidth: 1.5 } },
      },
      {
        type: "heatmap",
        data: cells.filter((c) => !c.scored).map(point),
        itemStyle: { color: COLORS.paper, borderColor: COLORS.thin, borderWidth: 1 },
      },
    ],
  };
}

type Interval = { label: string; value: number | null; low: number | null; high: number | null };

function intervalSeries(points: (Interval & { thin?: boolean })[], horizontal: boolean) {
  const ends = (p: Interval, i: number) =>
    horizontal ? [[p.low, i], [p.high, i]] : [[i, p.low], [i, p.high]];
  return [
    {
      type: "custom",
      renderItem: (_: unknown, api: { value: (dim: number) => number; coord: (v: number[]) => number[] }) => {
        const i = api.value(horizontal ? 1 : 0);
        const p = points[i];
        if (p.low === null || p.high === null) return null;
        const [a, b] = ends(p, i).map((v) => api.coord(v as number[]));
        return {
          type: "line",
          shape: { x1: a[0], y1: a[1], x2: b[0], y2: b[1] },
          style: { stroke: p.thin ? COLORS.thin : COLORS.link, lineWidth: 2 },
        };
      },
      // Each item holds a real coordinate (the interval's low end) so it never stretches the axis.
      data: points.map((p, i) => (horizontal ? [p.low ?? 0, i] : [i, p.low ?? 0])),
      silent: true,
      z: 1,
    },
    {
      type: "scatter",
      symbolSize: 9,
      z: 2,
      data: points.map((p, i) => ({
        value: horizontal ? [p.value, i] : [i, p.value],
        point: p,
        itemStyle: p.thin
          ? { color: COLORS.paper, borderColor: COLORS.thin, borderWidth: 1.5 }
          : { color: COLORS.link },
      })),
    },
  ];
}

/** Routes with their on-time share (dot) and 95 % interval (line), in the given order. */
export function routeIntervalOption(points: Interval[], font: string): EChartsCoreOption {
  const axis = axisStyle(font);
  return {
    grid: { left: 64, right: 24, top: 8, bottom: 44 },
    tooltip: {
      formatter: ({ data }: Tip) => {
        const { point } = data as { point: Interval & { extra?: string } };
        return `<b>Route ${point.label}</b><br/>On time ${pct(point.value)}<br/>95 % interval ${pct(point.low)} to ${pct(point.high)}${point.extra ? `<br/>${point.extra}` : ""}`;
      },
    },
    xAxis: {
      type: "value",
      min: 0,
      max: 1,
      ...axis,
      axisLabel: { ...axis.axisLabel, formatter: (v: number) => pct(v, 0) },
      name: "Share of arrivals on time (dot) and 95 % interval (line)",
      nameLocation: "middle",
      nameGap: 28,
    },
    yAxis: { type: "category", data: points.map((p) => p.label), inverse: true, ...axis },
    series: intervalSeries(points, true),
  };
}

/** One stop, hour by hour: on-time share (dot) and Wilson interval (line); thin hours hollow. */
export function hourlyIntervalOption(
  points: (Interval & { thin: boolean; events: number; p50: number | null; p90: number | null })[],
  font: string,
): EChartsCoreOption {
  const axis = axisStyle(font);
  return {
    grid: { left: 48, right: 16, top: 12, bottom: 44 },
    tooltip: {
      formatter: ({ data }: Tip) => {
        const { point: p } = data as { point: (typeof points)[number] };
        return [
          `<b>${p.label}</b>: ${count(p.events)} arrivals${p.thin ? " (too few to score)" : ""}`,
          `On time ${pct(p.value, 0)} (95 % ${pct(p.low, 0)} to ${pct(p.high, 0)})`,
          `Typical delay ${seconds(p.p50)}; bad day (p90) ${seconds(p.p90)}`,
        ].join("<br/>");
      },
    },
    xAxis: {
      type: "category",
      data: points.map((p) => p.label),
      ...axis,
      name: "Scheduled hour of the service day (+1 = after midnight)",
      nameLocation: "middle",
      nameGap: 30,
    },
    yAxis: {
      type: "value",
      min: 0,
      max: 1,
      ...axis,
      axisLabel: { ...axis.axisLabel, formatter: (v: number) => pct(v, 0) },
    },
    series: intervalSeries(points, false),
  };
}

export type MapStop = {
  stopId: string;
  label: string;
  lat: number;
  lon: number;
  events: number;
  share: number;
  display: string;
  sufficient: boolean;
  routeId: string;
  directionId: number | null;
  band: number;
  deltaPts: string | null;
};

/** Pre-aggregated 670 m neighborhood grid cell from public/data/map-grid/bus.json. */
export type MapGridCell = readonly [
  number, // lon
  number, // lat
  number, // events
  number | null, // arrival-weighted on-time share of sufficient stops in cell
  number, // stop count
  number, // sufficient stop count
  string, // busiest stop name in cell
  string, // busiest route in cell
  number, // diverging band id (0..4) or -1 for thin
  string | null, // pre-formatted signed delta vs bus stop median (e.g. "-8.5")
];

export type StreetPolyline = {
  coords: [number, number][];
  minLon: number;
  maxLon: number;
  minLat: number;
  maxLat: number;
};

export type SubwayLineGroup = { color: string; lines: [number, number][][] };

export type MapLayers = {
  /** Merged bus street grid (drawn only when zoomed in for buses, or when checked for subway). */
  streets: boolean;
  subway: boolean;
  /** Subway lines in MTA line colours instead of neutral slate. */
  lineColors: boolean;
};

export type Bbox = readonly [number, number, number, number]; // [minLon, maxLon, minLat, maxLat]

export type BandFilter = null | 0 | 1 | 2 | 3 | 4 | "thin";

/**
 * The map's fixed frame: New York City with a margin (every located stop and route shape lies
 * inside; a contract test checks the exported stops and basemap geometry).
 */
export const MAP_FRAME = { name: "nyc-frame", lon: [-74.26, -73.69], lat: [40.49, 40.94] } as const;
export const NYC_CENTER: readonly [number, number] = [-73.975, 40.705];
export const NYC_INITIAL_ZOOM = 1.04;
export const MAP_FRAME_GEOJSON = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      properties: { name: "frame" },
      geometry: {
        type: "Polygon",
        coordinates: [
          [
            [MAP_FRAME.lon[0], MAP_FRAME.lat[0]],
            [MAP_FRAME.lon[1], MAP_FRAME.lat[0]],
            [MAP_FRAME.lon[1], MAP_FRAME.lat[1]],
            [MAP_FRAME.lon[0], MAP_FRAME.lat[1]],
            [MAP_FRAME.lon[0], MAP_FRAME.lat[0]],
          ],
        ],
      },
    },
  ],
};

/** Bus mode switches automatically from 670 m grid to individual stops at this zoom. */
export const LOD_ZOOM_THRESHOLD = 2.0;
/** Merged bus street network loads and appears once zoomed into corridors. */
export const STREETS_FROM_ZOOM = 2.5;
export const MAP_ZOOM_LIMIT = { min: 1, max: 20 } as const;

export const BOROUGH_LABELS: readonly { name: string; value: readonly [number, number] }[] = [
  { name: "Manhattan", value: [-73.972, 40.778] },
  { name: "Bronx", value: [-73.868, 40.852] },
  { name: "Brooklyn", value: [-73.952, 40.642] },
  { name: "Queens", value: [-73.818, 40.728] },
  { name: "Staten Island", value: [-74.152, 40.58] },
];

export type MapBandSpec = {
  readonly id: number;
  readonly label: string;
  readonly range: string;
  readonly color: string;
  readonly max: number | null;
};

export type MapThinBand = {
  readonly id: "thin";
  readonly label: string;
  readonly color: string;
};

/** Look up a pre-assigned Python diverging band id (0..4) or -1 (thin) from the exported scale. */
export function bandMetaById(
  bandId: number,
  bands: readonly MapBandSpec[],
  thinBand: MapThinBand,
): { id: number | "thin"; label: string; color: string } {
  const match = bandId >= 0 ? bands.find((b) => b.id === bandId) : undefined;
  return match ?? thinBand;
}

export function stopDotSize(z: number, mode: string, compact: boolean): number {
  const scale = compact ? 0.85 : 1;
  if (mode === "subway") {
    if (z < 2.0) return +(6.0 * scale).toFixed(1);
    if (z < 4.5) return +(7.5 * scale).toFixed(1);
    if (z < 9.0) return +(9.5 * scale).toFixed(1);
    return +(11.5 * scale).toFixed(1);
  }
  if (z < 3.0) return +(4.4 * scale).toFixed(1);
  if (z < 5.5) return +(5.8 * scale).toFixed(1);
  if (z < 9.5) return +(7.8 * scale).toFixed(1);
  return +(10.0 * scale).toFixed(1);
}

export function gridCellSize(z: number, compact: boolean): number {
  const base = compact ? 4.4 : 6.2;
  return +(base * Math.min(1.5, Math.max(0.95, Math.pow(z, 0.45)))).toFixed(1);
}

/** Precompute bounding boxes once on load so zoomed-in street rendering only draws visible chains. */
export function indexStreets(lines: [number, number][][]): StreetPolyline[] {
  const out: StreetPolyline[] = [];
  for (let i = 0; i < lines.length; i++) {
    const coords = lines[i];
    if (coords.length < 2) continue;
    let minLon = Infinity;
    let maxLon = -Infinity;
    let minLat = Infinity;
    let maxLat = -Infinity;
    for (let j = 0; j < coords.length; j++) {
      const [lon, lat] = coords[j];
      if (lon < minLon) minLon = lon;
      if (lon > maxLon) maxLon = lon;
      if (lat < minLat) minLat = lat;
      if (lat > maxLat) maxLat = lat;
    }
    out.push({ coords, minLon, maxLon, minLat, maxLat });
  }
  return out;
}

const escapeHtml = (text: string) =>
  text.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] as string);

/** "NAME (STOP_ID)" from the export, split so the tooltip and panel can name each part. */
export function splitLabel(stop: Pick<MapStop, "label" | "stopId">): { name: string; id: string } {
  const suffix = ` (${stop.stopId})`;
  return stop.label.endsWith(suffix)
    ? { name: stop.label.slice(0, -suffix.length), id: stop.stopId }
    : { name: stop.label, id: stop.stopId };
}

function formatDeltaPts(deltaPts: string | null, modeWord: string, medianDisplay: string): string {
  if (!deltaPts) return "";
  return `${escapeHtml(deltaPts)} pts vs ${modeWord} stop median (${escapeHtml(medianDisplay)})`;
}

/** Opaque high-contrast tooltip for a 670 m neighborhood grid cell (bus city-wide view). */
export function gridTooltip(
  cell: MapGridCell,
  bands: readonly MapBandSpec[],
  thinBand: MapThinBand,
  busMedianDisplay: string,
  font: string,
): string {
  const [, , events, share, stopCount, suffCount, topStop, topRoute, bandId, deltaPts] = cell;
  const band = bandMetaById(bandId, bands, thinBand);
  const delta =
    suffCount > 0 && share !== null
      ? formatDeltaPts(deltaPts, "bus", busMedianDisplay)
      : "Under 10 arrivals across stops in this cell";
  return [
    `<div style="max-width:255px;white-space:normal;word-break:break-word;font-family:${escapeHtml(font)};color:${COLORS.ink};line-height:1.4;">`,
    `<div style="font-weight:700;font-size:13px;margin-bottom:4px;">Area near ${escapeHtml(topStop || "NYC block")}</div>`,
    `<div style="margin-bottom:6px;"><span style="display:inline-block;padding:1px 8px;border-radius:999px;font-size:11px;font-weight:600;color:#ffffff;background:${band.color};">${escapeHtml(band.label)}</span></div>`,
    `<div style="font-size:15px;font-weight:700;font-variant-numeric:tabular-nums;">${share !== null && suffCount > 0 ? `${pct(share)} on time` : "Not scored"}</div>`,
    `<div style="font-size:12px;color:${COLORS.muted};font-variant-numeric:tabular-nums;">${delta}</div>`,
    `<div style="font-size:12px;color:#334155;margin-top:6px;border-top:1px solid ${COLORS.rule};padding-top:5px;font-variant-numeric:tabular-nums;">${count(stopCount)} stops, ${count(events)} arrivals, busiest route ${escapeHtml(topRoute || "N/A")}</div>`,
    `<div style="font-size:11px;color:${COLORS.muted};margin-top:4px;">Zoom in or click cell to inspect individual stops</div>`,
    "</div>",
  ].join("");
}

/** Opaque high-contrast tooltip for an individual stop (clarifies stop-median comparison). */
export function stopTooltip(
  stop: MapStop,
  minEvents: number,
  modeWord: string,
  bands: readonly MapBandSpec[],
  thinBand: MapThinBand,
  medianDisplay: string,
  font = "sans-serif",
): string {
  const { name, id } = splitLabel(stop);
  const band = bandMetaById(stop.band, bands, thinBand);
  const delta = stop.sufficient
    ? formatDeltaPts(stop.deltaPts, modeWord, medianDisplay)
    : `Too few arrivals to score (fewer than ${count(minEvents)})`;
  return [
    `<div style="max-width:265px;white-space:normal;word-break:break-word;font-family:${escapeHtml(font)};color:${COLORS.ink};line-height:1.4;">`,
    `<div style="font-weight:700;font-size:13px;">${escapeHtml(name)}</div>`,
    name !== id
      ? `<div style="font-size:11px;color:${COLORS.muted};margin-bottom:5px;font-variant-numeric:tabular-nums;">Stop ${escapeHtml(id)}</div>`
      : "",
    `<div style="margin-bottom:5px;"><span style="display:inline-block;padding:1px 8px;border-radius:999px;font-size:11px;font-weight:600;color:#ffffff;background:${band.color};">${escapeHtml(band.label)}</span></div>`,
    `<div style="font-size:15px;font-weight:700;font-variant-numeric:tabular-nums;">${stop.sufficient ? `${escapeHtml(stop.display)} on time` : "Not scored"}</div>`,
    `<div style="font-size:12px;color:${COLORS.muted};font-variant-numeric:tabular-nums;">${delta}</div>`,
    `<div style="font-size:12px;color:#334155;margin-top:6px;border-top:1px solid ${COLORS.rule};padding-top:5px;font-variant-numeric:tabular-nums;">${count(stop.events)} arrival${stop.events === 1 ? "" : "s"} observed, all routes, both days (busiest route ${escapeHtml(stop.routeId || "N/A")})</div>`,
    `<div style="font-size:11px;color:${COLORS.muted};margin-top:4px;">On time: at most 1 min early, at most 5 min late. Click stop to pin details.</div>`,
    "</div>",
  ]
    .filter(Boolean)
    .join("");
}

export type HcmcMapWard = {
  ward_id: string;
  ward_name: string;
  area_display: string;
  active_stops: number;
  distinct_routes: number;
  coverage_any_400m_share: number;
  coverage_freq_conservative_share: number;
  coverage_freq_midpoint_share: number;
  coverage_any_display: string;
  coverage_freq_cons_display: string;
  coverage_freq_mid_display: string;
};

export type HcmcMetricKey = "any" | "freq_cons" | "freq_mid";

/**
 * Ward-level choropleth + optional bus corridors & stops for BR11 (Ho Chi Minh City), drawn from
 * self-hosted /basemap/hcmc.json (no map tiles, no third-party requests).
 */
export function hcmcChoroplethOption(
  mapName: string,
  wards: HcmcMapWard[],
  routes: number[][][],
  stops: [number, number, number, boolean][],
  metric: HcmcMetricKey,
  metricLabel: string,
  showRoutes: boolean,
  showStops: boolean,
  font: string,
): EChartsCoreOption {
  const byId = new Map(wards.map((w) => [w.ward_id, w]));
  const pickValue = (w: HcmcMapWard) =>
    metric === "any"
      ? w.coverage_any_400m_share
      : metric === "freq_cons"
        ? w.coverage_freq_conservative_share
        : w.coverage_freq_midpoint_share;

  const series: Record<string, unknown>[] = [
    {
      name: metricLabel,
      type: "map",
      geoIndex: 0,
      data: wards.map((w) => ({ name: w.ward_id, value: pickValue(w) })),
    },
  ];

  if (showRoutes && routes.length) {
    series.push({
      id: "hcmc-routes",
      type: "lines",
      coordinateSystem: "geo",
      polyline: true,
      silent: true,
      large: true,
      largeThreshold: 0,
      z: 2,
      data: routes.map((coords) => ({ coords })),
      lineStyle: { color: COLORS.ink, width: 0.9, opacity: 0.35 },
    });
  }

  if (showStops && stops.length) {
    const freqStops = stops.filter((s) => s[3]).map((s) => [s[0], s[1], s[2]]);
    const otherStops = stops.filter((s) => !s[3]).map((s) => [s[0], s[1], s[2]]);
    if (otherStops.length) {
      series.push({
        id: "hcmc-stops-other",
        type: "scatter",
        coordinateSystem: "geo",
        silent: true,
        large: true,
        largeThreshold: 0,
        z: 3,
        symbolSize: 3,
        data: otherStops,
        itemStyle: { color: COLORS.muted, opacity: 0.55 },
      });
    }
    if (freqStops.length) {
      series.push({
        id: "hcmc-stops-freq",
        type: "scatter",
        coordinateSystem: "geo",
        silent: true,
        large: true,
        largeThreshold: 0,
        z: 4,
        symbolSize: 4,
        data: freqStops,
        itemStyle: { color: COLORS.accent, opacity: 0.78 },
      });
    }
  }

  return {
    tooltip: {
      trigger: "item",
      textStyle: { fontFamily: font, fontSize: 12 },
      formatter: (params: { name?: string }) => {
        const w = params.name ? byId.get(params.name) : undefined;
        if (!w) return "";
        return [
          `<b lang="vi">${escapeHtml(w.ward_name)}</b>`,
          `Area: ${escapeHtml(w.area_display)}, ${count(w.active_stops)} stops, ${count(w.distinct_routes)} routes`,
          `400 m (any stop): <b>${escapeHtml(w.coverage_any_display)}</b>`,
          `≥ 4 buses/h (conservative): <b>${escapeHtml(w.coverage_freq_cons_display)}</b>`,
          `≥ 4 buses/h (midpoint): ${escapeHtml(w.coverage_freq_mid_display)}`,
        ].join("<br/>");
      },
    },
    visualMap: {
      seriesIndex: 0,
      min: 0,
      max: 1,
      orient: "horizontal",
      top: 4,
      left: "center",
      itemWidth: 10,
      itemHeight: 160,
      calculable: false,
      text: ["100 % covered", "0 %"],
      textStyle: { color: COLORS.muted, fontFamily: font, fontSize: 12 },
      inRange: { color: [...COLORS.sequential] },
    },
    geo: {
      map: mapName,
      roam: true,
      aspectScale: Math.cos((10.77 * Math.PI) / 180),
      layoutCenter: ["50%", "54%"],
      layoutSize: "88%",
      scaleLimit: { min: 0.9, max: 18 },
      itemStyle: { areaColor: COLORS.panel, borderColor: COLORS.paper, borderWidth: 0.8 },
      emphasis: {
        label: { show: false },
        itemStyle: { areaColor: COLORS.accent, borderColor: COLORS.ink, borderWidth: 1.2 },
      },
    },
    series,
  };
}
