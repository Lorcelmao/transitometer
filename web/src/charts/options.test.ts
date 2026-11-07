import { describe, expect, it } from "vitest";

import {
  bandColors,
  heatmapOption,
  hourlyIntervalOption,
  MAP_BANDS,
  routeIntervalOption,
  stopMapSeries,
  stopTooltip,
  type MapStop,
} from "@/charts/options";

describe("stop map", () => {
  const stop = (i: number, share: number, events: number, sufficient = true): MapStop => ({
    stopId: `S${i}`,
    label: `STOP ${i} (S${i})`,
    lat: 40.7 + i / 1000,
    lon: -73.9,
    events,
    share,
    display: `${(share * 100).toFixed(1)} %`,
    sufficient,
  });
  const stops = [stop(0, 0, 50), stop(1, 0.55, 300), stop(2, 1, 2000), stop(3, 0.4, 4, false)];
  const background = { streets: [[[-73.9, 40.7], [-73.8, 40.7]]] as [number, number][][], subway: [] };
  const layers = { streets: true, subway: true, lineColors: false };

  it("draws every stop exactly once and keeps its index for the tooltip and the click", () => {
    const series = stopMapSeries(stops, background, layers, true) as { type: string; data: number[][] }[];
    const indexes = series.filter((s) => s.type === "scatter").flatMap((s) => s.data.map((d) => d[2]));
    expect(indexes.sort()).toEqual([0, 1, 2, 3]);
    expect(series.some((s) => s.type === "lines")).toBe(true);
  });

  it("leaves the street layer out until it should show, and never sends an empty series", () => {
    const series = stopMapSeries(stops, background, layers, false) as { type: string; data: unknown[] }[];
    expect(series.some((s) => s.type === "lines")).toBe(false);
    expect(series.every((s) => s.data.length > 0)).toBe(true);
    expect(stopMapSeries(stops, null, layers, true).every((s) => s.type === "scatter")).toBe(true);
  });

  it("has one colour per 10 % band, from the ramp's ends", () => {
    const colors = bandColors(["#000000", "#ffffff"]);
    expect(colors).toHaveLength(MAP_BANDS);
    expect(colors[0] < colors[MAP_BANDS - 1]).toBe(true);
  });

  it("explains every line of the tooltip and escapes the stop name", () => {
    const text = stopTooltip({ ...stop(1, 0.5, 300), label: "A & <B> (S1)" }, 10);
    expect(text).toContain("A &amp; &lt;B&gt;");
    expect(text).toContain("Stop S1");
    expect(text).toContain("300 arrivals observed, all routes, both days");
    expect(text).toContain("at most 1 min early, at most 5 min late");
    expect(stopTooltip(stop(3, 0.4, 4, false), 10)).toContain("Too few arrivals to score (fewer than 10)");
  });
});

type Series = { type: string; data: { value: number[] }[] | number[][] };

describe("chart options only map exported fields to marks", () => {
  const cells = [
    { route_id: "B1", service_hour: 7, events: 40, on_time_share: 0.5, late_share: 0.4, median_delay_s: 120, scored: true },
    { route_id: "B1", service_hour: 8, events: 3, on_time_share: 1, late_share: 0, median_delay_s: 10, scored: false },
    { route_id: "M15", service_hour: 7, events: 55, on_time_share: 0.8, late_share: 0.1, median_delay_s: 30, scored: true },
  ];

  it("heatmap keeps the exported route order and splits scored from thin cells", () => {
    const option = heatmapOption(cells, ["M15", "B1"], "mono") as { yAxis: { data: string[] }; series: Series[] };
    expect(option.yAxis.data).toEqual(["M15", "B1"]);
    const [scored, thin] = option.series as { data: { value: number[] }[] }[];
    expect(scored.data.map((d) => d.value)).toEqual([
      [0, 1, 0.5],
      [0, 0, 0.8],
    ]);
    expect(thin.data.map((d) => d.value)).toEqual([[1, 1, 1]]);
  });

  it("route intervals stay on a 0-100 % axis whatever the number of routes", () => {
    const points = Array.from({ length: 20 }, (_, i) => ({ label: `R${i}`, value: 0.3, low: 0.2, high: 0.4 }));
    const option = routeIntervalOption(points, "mono") as { xAxis: { min: number; max: number }; series: Series[] };
    expect(option.xAxis.min).toBe(0);
    expect(option.xAxis.max).toBe(1);
    // the interval series must carry real x coordinates, never the row index
    for (const item of option.series[0].data as number[][]) expect(item[0]).toBeLessThanOrEqual(1);
  });

  it("hourly intervals mark thin hours as hollow", () => {
    const option = hourlyIntervalOption(
      [
        { label: "7", value: 0.5, low: 0.3, high: 0.7, thin: false, events: 20, p50: 60, p90: 200 },
        { label: "8", value: 1, low: 0.2, high: 1, thin: true, events: 2, p50: 0, p90: 10 },
      ],
      "mono",
    ) as { series: { data: { itemStyle: { color: string } }[] }[] };
    const dots = option.series[1].data;
    expect(dots[0].itemStyle.color).not.toBe(dots[1].itemStyle.color);
  });
});
