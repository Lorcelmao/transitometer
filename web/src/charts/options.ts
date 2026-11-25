/**
 * ECharts options for the geometric charts (heatmap, route intervals, hourly intervals, stop map).
 *
 * These map exported fields to marks and nothing else: rows arrive filtered, ordered and flagged
 * by the Python views (which routes, which cells are scored, the interval bounds). No sorting,
 * filtering, threshold or arithmetic on metric values happens here.
 */
import type { EChartsCoreOption } from "echarts/core";

import { axisStyle, COLORS } from "@/charts/theme";
import { count, pct, seconds, serviceHour } from "@/lib/format";

type Tip = { data: unknown };

/** Route x hour heatmap of on-time share; thin cells (not scored) are drawn as outlines. */
export function heatmapOption(
  cells: {
    route_id: string;
    service_hour: number;
    events: number;
    on_time_share: number | null;
    late_share: number | null;
    median_delay_s: number | null;
    scored: boolean;
  }[],
  routes: string[],
  font: string,
): EChartsCoreOption {
  const hours = Array.from(new Set(cells.map((c) => c.service_hour))).sort((a, b) => a - b);
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
          `<b>Route ${cell.route_id}</b>, ${serviceHour(cell.service_hour)}`,
          `${count(cell.events)} arrivals${cell.scored ? "" : " (too few to score)"}`,
          `On time ${pct(cell.on_time_share)}, late ${pct(cell.late_share)}`,
          `Median delay ${seconds(cell.median_delay_s)}`,
        ].join("<br/>");
      },
    },
    xAxis: {
      type: "category",
      data: hours.map((h) => (h >= 24 ? `${String(h - 24).padStart(2, "0")}+1` : String(h).padStart(2, "0"))),
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
export const NYC_BOROUGHS_MAP = "nyc-boroughs";
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
  readonly id: 0 | 1 | 2 | 3 | 4;
  readonly label: string;
  readonly range: string;
  readonly color: string;
  readonly max: number;
};

/**
 * Unified 5-class WCAG AA diverging scale anchored around the equal-weighted bus stop median
 * (45.5 %). Every colour exceeds 4.1:1 contrast on #f4f6f9 land and 4.4:1 on #ffffff.
 */
export const MAP_DIVERGING_BANDS: readonly MapBandSpec[] = [
  { id: 0, label: "Critical", range: "under 30 %", color: COLORS.mapDiverging[0], max: 0.3 },
  { id: 1, label: "Poor", range: "30 to 40 %", color: COLORS.mapDiverging[1], max: 0.4 },
  { id: 2, label: "Typical", range: "40 to 50 %", color: COLORS.mapDiverging[2], max: 0.5 },
  { id: 3, label: "Above typical", range: "50 to 65 %", color: COLORS.mapDiverging[3], max: 0.65 },
  { id: 4, label: "Reliable", range: "65 % or more", color: COLORS.mapDiverging[4], max: 2.0 },
] as const;

export function bandIndex(share: number | null | undefined): 0 | 1 | 2 | 3 | 4 | -1 {
  if (share === null || share === undefined || Number.isNaN(share)) return -1;
  if (share < 0.3) return 0;
  if (share < 0.4) return 1;
  if (share < 0.5) return 2;
  if (share < 0.65) return 3;
  return 4;
}

export function bandMeta(
  share: number | null | undefined,
  sufficient: boolean,
): { id: 0 | 1 | 2 | 3 | 4 | "thin"; label: string; color: string } {
  if (!sufficient || share === null || share === undefined) {
    return { id: "thin", label: "Under 10 arrivals", color: COLORS.mapThinStroke };
  }
  const idx = bandIndex(share);
  return idx === -1 ? { id: "thin", label: "Under 10 arrivals", color: COLORS.mapThinStroke } : MAP_DIVERGING_BANDS[idx];
}

export function zoomBucket(z: number): number {
  if (z < LOD_ZOOM_THRESHOLD) return 0;
  if (z < 3.0) return 1;
  if (z < 5.5) return 2;
  if (z < 9.5) return 3;
  return 4;
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

function formatDeltaPts(share: number | null, medianShare: number | null, modeWord: string, medianDisplay: string): string {
  if (share === null || medianShare === null) return "";
  const pts = ((share - medianShare) * 100).toFixed(1);
  const signed = Number(pts) >= 0 ? `+${pts}` : pts;
  return `${signed} pts vs ${modeWord} stop median (${escapeHtml(medianDisplay)})`;
}

/** Opaque high-contrast tooltip for a 670 m neighborhood grid cell (bus city-wide view). */
export function gridTooltip(
  cell: MapGridCell,
  busMedianShare: number | null,
  busMedianDisplay: string,
  font: string,
): string {
  const [, , events, share, stopCount, suffCount, topStop, topRoute] = cell;
  const band = bandMeta(share, suffCount > 0);
  const delta =
    suffCount > 0 && share !== null
      ? formatDeltaPts(share, busMedianShare, "bus", busMedianDisplay)
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
  medianShare: number | null,
  medianDisplay: string,
  font = "sans-serif",
): string {
  const { name, id } = splitLabel(stop);
  const band = bandMeta(stop.share, stop.sufficient);
  const delta = stop.sufficient
    ? formatDeltaPts(stop.share, medianShare, modeWord, medianDisplay)
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

export type StopMapSeriesParams = {
  mode: string;
  zoom: number;
  compact: boolean;
  useGrid: boolean;
  gridCells: readonly MapGridCell[];
  stops: readonly MapStop[];
  bbox: Bbox | null;
  filterBand: BandFilter;
  layers: MapLayers;
  subway: readonly SubwayLineGroup[] | null;
  streets: readonly StreetPolyline[] | null;
  selectedStop: { lon: number; lat: number } | null;
  font: string;
};

/**
 * Builds at most 9 lightweight Canvas series (lines + 5 diverging bands + non-large thin dots +
 * borough labels + pinned selection ring). Uses pure numeric [lon, lat, index] tuples and
 * ECharts progressive chunked rendering to prevent > 200 ms long tasks on throttled mobile CPUs.
 */
export function stopMapSeries(params: StopMapSeriesParams): {
  series: Record<string, unknown>[];
  visibleCount: number;
} {
  const {
    mode,
    zoom,
    compact,
    useGrid,
    gridCells,
    stops,
    bbox,
    filterBand,
    layers,
    subway,
    streets,
    selectedStop,
    font,
  } = params;
  const series: Record<string, unknown>[] = [];
  const streetZoomMin = compact ? 3.2 : STREETS_FROM_ZOOM;
  const showStreets = mode === "bus" && layers.streets && streets && zoom >= streetZoomMin;

  if (showStreets) {
    const visibleLines: { coords: [number, number][] }[] = [];
    for (let i = 0; i < streets.length; i++) {
      const s = streets[i];
      if (bbox && (s.maxLon < bbox[0] || s.minLon > bbox[1] || s.maxLat < bbox[2] || s.minLat > bbox[3])) {
        continue;
      }
      visibleLines.push({ coords: s.coords });
    }
    if (visibleLines.length) {
      series.push({
        id: "streets",
        type: "lines",
        coordinateSystem: "geo",
        polyline: true,
        silent: true,
        animation: false,
        large: true,
        largeThreshold: 300,
        progressive: 450,
        progressiveThreshold: 450,
        z: 2,
        data: visibleLines,
        lineStyle: { color: COLORS.mapStreets, width: zoom >= 5 ? 1.15 : 0.8, opacity: 0.78 },
      });
    }
  }

  if (layers.subway && subway && (mode === "subway" || zoom >= STREETS_FROM_ZOOM)) {
    if (layers.lineColors) {
      subway.forEach((group, i) => {
        if (!group.lines.length) return;
        series.push({
          id: `subway-${i}`,
          type: "lines",
          coordinateSystem: "geo",
          polyline: true,
          silent: true,
          animation: false,
          z: 3,
          data: group.lines.map((coords) => ({ coords })),
          lineStyle: { color: group.color, width: 1.75, opacity: 0.85 },
        });
      });
    } else {
      const merged = subway.flatMap((g) => g.lines.map((coords) => ({ coords })));
      if (merged.length) {
        series.push({
          id: "subway-all",
          type: "lines",
          coordinateSystem: "geo",
          polyline: true,
          silent: true,
          animation: false,
          z: 3,
          data: merged,
          lineStyle: { color: COLORS.mapSubway, width: 1.35, opacity: 0.82 },
        });
      }
    }
  }

  let visibleCount = 0;

  if (useGrid) {
    const buckets: [number, number, number][][] = [[], [], [], [], []];
    const thinPts: [number, number, number][] = [];
    for (let i = 0; i < gridCells.length; i++) {
      const c = gridCells[i];
      const share = c[3];
      const suff = c[5] > 0 && share !== null;
      const bi = suff ? bandIndex(share) : -1;
      if (filterBand !== null) {
        if (filterBand === "thin" && suff) continue;
        if (typeof filterBand === "number" && bi !== filterBand) continue;
      }
      const pt: [number, number, number] = [c[0], c[1], i];
      if (!suff || bi === -1) thinPts.push(pt);
      else buckets[bi].push(pt);
      visibleCount++;
    }
    const sz = gridCellSize(zoom, compact);
    for (const bi of [4, 3, 2, 1, 0] as const) {
      if (!buckets[bi].length) continue;
      series.push({
        id: `band-${bi}`,
        type: "scatter",
        coordinateSystem: "geo",
        animation: false,
        symbol: "roundRect",
        symbolSize: sz,
        z: 5 + (4 - bi),
        itemStyle: {
          color: MAP_DIVERGING_BANDS[bi].color,
          borderColor: COLORS.surface,
          borderWidth: 0.65,
          opacity: 0.94,
        },
        emphasis: { scale: 1.35, itemStyle: { borderColor: COLORS.ink, borderWidth: 2 } },
        data: buckets[bi],
      });
    }
    if (thinPts.length) {
      series.push({
        id: "band-thin",
        type: "scatter",
        coordinateSystem: "geo",
        animation: false,
        symbol: "roundRect",
        symbolSize: Math.max(4, sz - 1),
        z: 4,
        itemStyle: { color: COLORS.surface, borderColor: COLORS.mapThinStroke, borderWidth: 1.2 },
        data: thinPts,
      });
    }
  } else {
    const buckets: [number, number, number][][] = [[], [], [], [], []];
    const thinPts: [number, number, number][] = [];
    for (let i = 0; i < stops.length; i++) {
      const s = stops[i];
      if (bbox && (s.lon < bbox[0] || s.lon > bbox[1] || s.lat < bbox[2] || s.lat > bbox[3])) {
        continue;
      }
      const bi = s.sufficient ? bandIndex(s.share) : -1;
      if (filterBand !== null) {
        if (filterBand === "thin" && s.sufficient) continue;
        if (typeof filterBand === "number" && bi !== filterBand) continue;
      }
      const pt: [number, number, number] = [s.lon, s.lat, i];
      if (!s.sufficient || bi === -1) thinPts.push(pt);
      else buckets[bi].push(pt);
      visibleCount++;
    }
    const sz = stopDotSize(zoom, mode, compact);
    const strokeW = zoom >= 4.5 ? 1.2 : 0.8;
    // Lower largeThreshold on mobile so 4x-throttled CPUs use Float32 Canvas batch + progressive slices.
    const largeCutoff = compact ? 500 : 1600;
    const useLarge = mode === "bus" && visibleCount > largeCutoff;
    for (const bi of [4, 3, 2, 1, 0] as const) {
      if (!buckets[bi].length) continue;
      series.push({
        id: `band-${bi}`,
        type: "scatter",
        coordinateSystem: "geo",
        animation: false,
        large: useLarge,
        largeThreshold: largeCutoff,
        progressive: useLarge ? 500 : 0,
        progressiveThreshold: useLarge ? 500 : 3000,
        progressiveChunkMode: "mod",
        symbol: "circle",
        symbolSize: sz,
        z: 6 + (4 - bi),
        itemStyle: {
          color: MAP_DIVERGING_BANDS[bi].color,
          borderColor: COLORS.surface,
          borderWidth: strokeW,
          opacity: 0.95,
        },
        emphasis: { scale: 1.45, itemStyle: { borderColor: COLORS.ink, borderWidth: 2.2 } },
        data: buckets[bi],
      });
    }
    if (thinPts.length) {
      // Keep <= 55 low-volume hollow dots non-large so Canvas never draws square fallback artifacts.
      series.push({
        id: "band-thin",
        type: "scatter",
        coordinateSystem: "geo",
        animation: false,
        symbol: "circle",
        symbolSize: Math.max(4, sz - 0.5),
        z: 5,
        itemStyle: { color: COLORS.surface, borderColor: COLORS.mapThinStroke, borderWidth: 1.4 },
        emphasis: { scale: 1.45, itemStyle: { borderColor: COLORS.ink, borderWidth: 2.2 } },
        data: thinPts,
      });
    }
  }

  if (zoom < 2.6) {
    series.push({
      id: "borough-labels",
      type: "scatter",
      coordinateSystem: "geo",
      silent: true,
      animation: false,
      symbolSize: 0,
      z: 16,
      label: {
        show: true,
        formatter: "{b}",
        color: "#1e293b",
        fontFamily: font,
        fontWeight: 700,
        fontSize: compact ? 10 : 12,
        textBorderColor: "rgba(255, 255, 255, 0.92)",
        textBorderWidth: 3.5,
      },
      data: BOROUGH_LABELS,
    });
  }

  if (selectedStop) {
    series.push({
      id: "selected-ring",
      type: "scatter",
      coordinateSystem: "geo",
      silent: true,
      animation: false,
      z: 20,
      symbol: "circle",
      symbolSize: Math.max(14, stopDotSize(zoom, mode, compact) + 7),
      itemStyle: { color: "transparent", borderColor: COLORS.ink, borderWidth: 2.5 },
      data: [[selectedStop.lon, selectedStop.lat]],
    });
  }

  return { series, visibleCount };
}

/**
 * Base ECharts option for the NYC Stop map using self-hosted NYC DCP borough polygons and MTA
 * static GTFS shapes (no map tiles, no third-party requests, zero shadowBlur).
 */
export function stopMapBaseOption(params: {
  mapName: string;
  font: string;
  tooltipFormatter: (tip: { data?: unknown; value?: unknown }) => string;
  series: Record<string, unknown>[];
}): EChartsCoreOption {
  const { mapName, font, tooltipFormatter, series } = params;
  return {
    animation: false,
    backgroundColor: COLORS.mapWater,
    textStyle: { fontFamily: font },
    tooltip: {
      trigger: "item",
      confine: true,
      backgroundColor: COLORS.surface,
      borderColor: "#64748b",
      borderWidth: 1,
      padding: [10, 12],
      textStyle: { color: COLORS.ink, fontFamily: font, fontSize: 13 },
      extraCssText:
        "box-shadow: 0 10px 24px rgba(15, 23, 42, 0.18); border-radius: 8px; opacity: 1; white-space: normal; max-width: 290px;",
      formatter: tooltipFormatter,
    },
    geo: {
      map: mapName,
      roam: true,
      silent: true,
      zoom: NYC_INITIAL_ZOOM,
      center: [...NYC_CENTER],
      scaleLimit: { ...MAP_ZOOM_LIMIT },
      boundingCoords: [
        [MAP_FRAME.lon[0], MAP_FRAME.lat[1]],
        [MAP_FRAME.lon[1], MAP_FRAME.lat[0]],
      ],
      layoutCenter: ["50%", "50%"],
      layoutSize: "96%",
      itemStyle: {
        areaColor: COLORS.mapLand,
        borderColor: COLORS.mapShoreline,
        borderWidth: 1,
      },
      emphasis: { disabled: true },
      label: { show: false },
    },
    series,
  };
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
