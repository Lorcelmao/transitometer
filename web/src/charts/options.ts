/**
 * ECharts options for the three geometric charts (heatmap, route intervals, hourly intervals).
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

/**
 * Located stops on longitude/latitude axes, no basemap: the stops themselves trace the city.
 * Axis spans are padded so one kilometre is as long east-west as north-south in a square chart
 * (an equirectangular projection corrected by cos(latitude), exact enough at city scale).
 */
export function stopMapOption(stops: MapStop[], font: string): EChartsCoreOption {
  const lats = stops.map((s) => s.lat);
  const lons = stops.map((s) => s.lon);
  const [minLat, maxLat, minLon, maxLon] = [Math.min(...lats), Math.max(...lats), Math.min(...lons), Math.max(...lons)];
  const midLat = (minLat + maxLat) / 2;
  const squeeze = Math.cos((midLat * Math.PI) / 180);
  const half = Math.max(maxLat - minLat, (maxLon - minLon) * squeeze) / 2 + 0.005;
  const midLon = (minLon + maxLon) / 2;
  const size = (s: MapStop) => Math.max(3, Math.min(14, Math.sqrt(s.events) / 2.5));
  const point = (s: MapStop) => ({ value: [s.lon, s.lat, s.share], stop: s, symbolSize: size(s) });
  const hidden = { show: false };
  return {
    grid: { left: 8, right: 8, top: 40, bottom: 8 },
    tooltip: {
      formatter: ({ data }: Tip) => {
        const { stop } = data as { stop: MapStop };
        return `<b>${stop.label}</b><br/>${count(stop.events)} arrivals · on time ${stop.display}${stop.sufficient ? "" : " (too few to score)"}<br/>Click for the stop's hours`;
      },
    },
    xAxis: { type: "value", min: midLon - half / squeeze, max: midLon + half / squeeze, axisLine: hidden, axisLabel: hidden, axisTick: hidden, splitLine: hidden },
    yAxis: { type: "value", min: midLat - half, max: midLat + half, axisLine: hidden, axisLabel: hidden, axisTick: hidden, splitLine: hidden },
    visualMap: {
      seriesIndex: 0,
      dimension: 2,
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
        type: "scatter",
        large: false,
        data: stops.filter((s) => s.sufficient).map(point),
        itemStyle: { opacity: 0.85, borderColor: COLORS.paper, borderWidth: 0.5 },
        emphasis: { itemStyle: { borderColor: COLORS.ink, borderWidth: 1.5 } },
        z: 2,
      },
      {
        type: "scatter",
        data: stops.filter((s) => !s.sufficient).map(point),
        itemStyle: { color: "transparent", borderColor: COLORS.thin, borderWidth: 1 },
        z: 1,
      },
    ],
  };
}
