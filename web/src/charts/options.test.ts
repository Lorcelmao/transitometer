import { describe, expect, it } from "vitest";

import {
  bandIndex,
  gridTooltip,
  heatmapOption,
  hourlyIntervalOption,
  indexStreets,
  MAP_DIVERGING_BANDS,
  routeIntervalOption,
  stopMapSeries,
  stopTooltip,
  type MapGridCell,
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
    routeId: "M4",
    directionId: 0,
  });
  const stops = [
    stop(0, 0.2, 50),
    stop(1, 0.35, 120),
    stop(2, 0.45, 220),
    stop(3, 0.55, 300),
    stop(4, 0.85, 2000),
    stop(5, 0.4, 4, false),
  ];
  const streets = indexStreets([[[-73.92, 40.7], [-73.88, 40.7]], [[-74.2, 40.52], [-74.18, 40.52]]]);
  const layers = { streets: true, subway: true, lineColors: false };

  it("assigns every stop to its diverging band once and keeps thin stops non-large", () => {
    const { series, visibleCount } = stopMapSeries({
      mode: "bus",
      zoom: 3.5,
      compact: false,
      useGrid: false,
      gridCells: [],
      stops,
      bbox: [-73.95, -73.85, 40.68, 40.74],
      filterBand: null,
      layers,
      subway: [],
      streets,
      selectedStop: null,
      font: "sans-serif",
    });
    expect(visibleCount).toBe(6);
    const scatter = series.filter((s) => s.type === "scatter" && String(s.id).startsWith("band-")) as {
      id: string;
      large?: boolean;
      data: number[][];
    }[];
    const indexes = scatter.flatMap((s) => s.data.map((d) => d[2]));
    expect(indexes.sort((a, b) => a - b)).toEqual([0, 1, 2, 3, 4, 5]);
    const thin = scatter.find((s) => s.id === "band-thin");
    expect(thin?.large).toBeUndefined();
    // Only the street inside the Manhattan bbox should survive viewport culling
    const streetSeries = series.find((s) => s.id === "streets") as { data: unknown[] } | undefined;
    expect(streetSeries?.data).toHaveLength(1);
  });

  it("renders the 670 m grid at city zoom and leaves streets out before STREETS_FROM_ZOOM", () => {
    const cells: MapGridCell[] = [
      [-73.97, 40.75, 400, 0.25, 6, 6, "5 AV/E 72 ST", "M4"],
      [-73.95, 40.72, 8, null, 2, 0, "TINY STOP", "B24"],
    ];
    const { series, visibleCount } = stopMapSeries({
      mode: "bus",
      zoom: 1.04,
      compact: false,
      useGrid: true,
      gridCells: cells,
      stops: [],
      bbox: null,
      filterBand: null,
      layers,
      subway: [],
      streets,
      selectedStop: null,
      font: "sans-serif",
    });
    expect(visibleCount).toBe(2);
    expect(series.some((s) => s.id === "streets")).toBe(false);
    expect(series.some((s) => s.id === "borough-labels")).toBe(true);
    expect(series.some((s) => s.id === "band-0")).toBe(true);
    expect(series.some((s) => s.id === "band-thin")).toBe(true);
  });

  it("maps shares onto the 5 diverging WCAG AA bands", () => {
    expect(MAP_DIVERGING_BANDS).toHaveLength(5);
    expect(bandIndex(0.1)).toBe(0);
    expect(bandIndex(0.35)).toBe(1);
    expect(bandIndex(0.455)).toBe(2);
    expect(bandIndex(0.6)).toBe(3);
    expect(bandIndex(0.8)).toBe(4);
    expect(bandIndex(null)).toBe(-1);
  });

  it("formats stop and grid tooltips with HTML escaping and equal-weighted stop median reference", () => {
    const text = stopTooltip(
      { ...stop(1, 0.25, 300), label: "A & <B> (S1)" },
      10,
      "bus",
      0.455,
      "45.5 %",
    );
    expect(text).toContain("A &amp; &lt;B&gt;");
    expect(text).toContain("Stop S1");
    expect(text).toContain("Critical");
    expect(text).toContain("-20.5 pts vs bus stop median (45.5 %)");
    expect(text).toContain("300 arrivals observed, all routes, both days");
    expect(stopTooltip(stop(3, 0.4, 4, false), 10, "bus", 0.455, "45.5 %")).toContain(
      "Too few arrivals to score (fewer than 10)",
    );

    const gridText = gridTooltip([-73.97, 40.75, 400, 0.25, 6, 6, "5 AV & E 72", "M4"], 0.455, "45.5 %", "sans-serif");
    expect(gridText).toContain("5 AV &amp; E 72");
    expect(gridText).toContain("bus stop median (45.5 %)");
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
