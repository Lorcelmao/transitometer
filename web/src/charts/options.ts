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
          `<b>Route ${cell.route_id}</b>, hour ${cell.service_hour}`,
          `${count(cell.events)} arrivals${cell.scored ? "" : " (too few to score)"}`,
          `On time ${pct(cell.on_time_share)} · late ${pct(cell.late_share)}`,
          `Median delay ${seconds(cell.median_delay_s)}`,
        ].join("<br/>");
      },
    },
    xAxis: {
      type: "category",
      data: hours.map(String),
      name: "Hour of the service day (scheduled time)",
      nameLocation: "middle",
      nameGap: 26,
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
      textStyle: { color: COLORS.muted, fontFamily: font, fontSize: 11 },
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
        return `<b>Route ${point.label}</b><br/>On time ${pct(point.value)}<br/>95 % interval ${pct(point.low)} – ${pct(point.high)}${point.extra ? `<br/>${point.extra}` : ""}`;
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
          `<b>Hour ${p.label}</b>: ${count(p.events)} arrivals${p.thin ? " (too few to score)" : ""}`,
          `On time ${pct(p.value, 0)} (95 % ${pct(p.low, 0)} – ${pct(p.high, 0)})`,
          `Typical delay ${seconds(p.p50)} · bad day (p90) ${seconds(p.p90)}`,
        ].join("<br/>");
      },
    },
    xAxis: {
      type: "category",
      data: points.map((p) => p.label),
      ...axis,
      name: "Hour of the service day (scheduled time)",
      nameLocation: "middle",
      nameGap: 28,
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
};

/** Background geometry (public/basemap/nyc.json): [lon, lat] polylines. */
export type MapBackground = {
  streets: [number, number][][];
  subway: { color: string; lines: [number, number][][] }[];
};

export type MapLayers = {
  /** Bus route shapes, which trace the streets (drawn only when `zoomedIn` or for subway stops). */
  streets: boolean;
  subway: boolean;
  /** Subway lines in the MTA's own colours instead of one neutral grey. */
  lineColors: boolean;
};

/**
 * The map's fixed frame: New York City with a margin (every located stop and route shape lies
 * inside; a contract test checks the exported stops). Registered once as an invisible geo map
 * (echarts-setup), so the geo component gives zoom, pan and the cos(latitude) aspect without tiles.
 */
export const MAP_FRAME = { name: "nyc-frame", lon: [-74.26, -73.69], lat: [40.49, 40.94] } as const;
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

/** Bus stops cover the street layer at city scale; it joins in once the view is zoomed this far. */
export const STREETS_FROM_ZOOM = 1.5;
export const MAP_ZOOM_LIMIT = { min: 1, max: 24 } as const;

/**
 * Colour and size scales of the stop dots, as steps: each (colour band, size) group is drawn as one
 * "large" series (a single path), which keeps zoom and pan fast with ~12,000 stops. The bands only
 * map the exported share to a colour, like a visual map; no metric is computed here.
 */
export const MAP_BANDS = 10;
export const MAP_SIZES = [3, 4.5, 6.5, 9, 13] as const;

function mix(a: string, b: string, t: number) {
  const channel = (hex: string, i: number) => parseInt(hex.slice(1 + 2 * i, 3 + 2 * i), 16);
  return `#${[0, 1, 2]
    .map((i) => Math.round(channel(a, i) + (channel(b, i) - channel(a, i)) * t).toString(16).padStart(2, "0"))
    .join("")}`;
}

/** The colour of each 10 %-wide band, interpolated along the sequential ramp. */
export function bandColors(ramp: readonly string[] = COLORS.sequential): string[] {
  return Array.from({ length: MAP_BANDS }, (_, i) => {
    const x = ((i + 0.5) / MAP_BANDS) * (ramp.length - 1);
    const k = Math.min(ramp.length - 2, Math.floor(x));
    return mix(ramp[k], ramp[k + 1], x - k);
  });
}

/** Dot size grows with the square root of arrivals, snapped to the nearest step. */
export function sizeClass(events: number): number {
  const size = Math.max(3, Math.min(14, Math.sqrt(events) / 2.5));
  let best = 0;
  MAP_SIZES.forEach((s, i) => {
    if (Math.abs(s - size) < Math.abs(MAP_SIZES[best] - size)) best = i;
  });
  return best;
}

const escapeHtml = (text: string) =>
  text.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] as string);

/** "NAME (STOP_ID)" from the export, split so the tooltip can name each part. */
export function splitLabel(stop: MapStop): { name: string; id: string } {
  const suffix = ` (${stop.stopId})`;
  return stop.label.endsWith(suffix)
    ? { name: stop.label.slice(0, -suffix.length), id: stop.stopId }
    : { name: stop.label, id: stop.stopId };
}

/** The tooltip, written to be read on its own (what each number counts). */
export function stopTooltip(stop: MapStop, minEvents: number): string {
  const { name, id } = splitLabel(stop);
  const muted = (text: string) => `<span style="color:${COLORS.muted}">${text}</span>`;
  return [
    `<b>${escapeHtml(name)}</b>`,
    name !== id ? muted(`Stop ${escapeHtml(id)}`) : "",
    `${count(stop.events)} arrival${stop.events === 1 ? "" : "s"} observed, all routes, both days`,
    stop.sufficient
      ? `<b>${escapeHtml(stop.display)}</b> on time ${muted("(at most 1 min early, at most 5 min late)")}`
      : muted(`Too few arrivals to score (fewer than ${count(minEvents)})`),
    muted("Click for the stop's hours"),
  ]
    .filter(Boolean)
    .join("<br/>");
}

/**
 * The map's series: background lines, then hollow (thin) stops, then scored stops by colour band
 * and size. Each stop's data item is [lon, lat, index into `stops`]. Hidden layers and empty groups
 * are left out (large-mode series do not take empty data).
 */
export function stopMapSeries(stops: MapStop[], background: MapBackground | null, layers: MapLayers, showStreets: boolean) {
  const colors = bandColors();
  const scored = colors.map(() => MAP_SIZES.map(() => [] as number[][]));
  const thin = MAP_SIZES.map(() => [] as number[][]);
  stops.forEach((s, i) => {
    const item = [s.lon, s.lat, i];
    const size = sizeClass(s.events);
    if (s.sufficient) scored[Math.min(MAP_BANDS - 1, Math.floor(s.share * MAP_BANDS))][size].push(item);
    else thin[size].push(item);
  });
  const large = { coordinateSystem: "geo", large: true, largeThreshold: 0 } as const;
  const series: Record<string, unknown>[] = [];
  if (background && layers.streets && showStreets) {
    series.push({
      ...large,
      id: "streets",
      type: "lines",
      polyline: true,
      silent: true,
      z: 1,
      data: background.streets.map((coords) => ({ coords })),
      lineStyle: { color: COLORS.rule, width: 0.7, opacity: 1 },
    });
  }
  if (background && layers.subway) {
    background.subway.forEach((line, i) =>
      series.push({
        ...large,
        id: `subway-${i}`,
        type: "lines",
        polyline: true,
        silent: true,
        z: 2,
        data: line.lines.map((coords) => ({ coords })),
        lineStyle: layers.lineColors
          ? { color: line.color, width: 1.8, opacity: 0.85 }
          : { color: COLORS.muted, width: 1.6, opacity: 0.55 },
      }),
    );
  }
  MAP_SIZES.forEach((size, j) => {
    if (thin[j].length)
      series.push({
        ...large,
        id: `thin-${j}`,
        type: "scatter",
        z: 3,
        symbolSize: size,
        data: thin[j],
        itemStyle: { color: "transparent", borderColor: COLORS.thin, borderWidth: 1 },
      });
  });
  colors.forEach((color, b) =>
    MAP_SIZES.forEach((size, j) => {
      if (scored[b][j].length)
        series.push({
          ...large,
          id: `band-${b}-${j}`,
          type: "scatter",
          z: 4 + j,
          symbolSize: size,
          data: scored[b][j],
          itemStyle: { color, opacity: 0.9 },
        });
    }),
  );
  return series;
}

/**
 * Every located stop on a zoomable frame of the city, over a background drawn from the MTA's own
 * route shapes (no map tiles, no third-party requests). `view` keeps the visitor's zoom and pan
 * when layers change.
 */
export function stopMapOption(
  stops: MapStop[],
  background: MapBackground | null,
  layers: MapLayers,
  showStreets: boolean,
  minEvents: number,
  view?: { center?: number[]; zoom?: number },
): EChartsCoreOption {
  return {
    tooltip: {
      formatter: ({ data }: Tip) => {
        const stop = Array.isArray(data) ? stops[data[2] as number] : undefined;
        return stop ? stopTooltip(stop, minEvents) : "";
      },
    },
    geo: {
      map: MAP_FRAME.name,
      roam: true,
      aspectScale: Math.cos((((MAP_FRAME.lat[0] + MAP_FRAME.lat[1]) / 2) * Math.PI) / 180),
      scaleLimit: { ...MAP_ZOOM_LIMIT },
      silent: true,
      itemStyle: { areaColor: "transparent", borderWidth: 0 },
      emphasis: { disabled: true },
      label: { show: false },
      left: 8,
      right: 8,
      top: 8,
      bottom: 8,
      ...(view?.center ? { center: view.center } : {}),
      ...(view?.zoom ? { zoom: view.zoom } : {}),
    },
    series: stopMapSeries(stops, background, layers, showStreets),
  };
}
