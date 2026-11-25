import { describe, expect, it } from "vitest";

import {
  bandMetaById,
  gridTooltip,
  heatmapOption,
  hourlyIntervalOption,
  routeIntervalOption,
  stopTooltip,
  type MapBandSpec,
  type MapStop,
  type MapThinBand,
} from "@/charts/options";

const SAMPLE_BANDS: readonly MapBandSpec[] = [
  { id: 0, label: "Critical", range: "under 30 %", color: "#b3261e", max: 0.3 },
  { id: 1, label: "Poor", range: "30 to 40 %", color: "#c2570a", max: 0.4 },
  { id: 2, label: "Typical", range: "40 to 50 %", color: "#64748b", max: 0.5 },
  { id: 3, label: "Above typical", range: "50 to 65 %", color: "#2b6cb0", max: 0.65 },
  { id: 4, label: "Reliable", range: "65 % or more", color: "#0b3b75", max: null },
];
const SAMPLE_THIN: MapThinBand = { id: "thin", label: "Under 10 arrivals", color: "#475569" };

describe("stop map", () => {
  const stop = (
    i: number,
    share: number,
    events: number,
    sufficient = true,
    band = 0,
    deltaPts: string | null = "-20.5",
  ): MapStop => ({
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
    band: sufficient ? band : -1,
    deltaPts: sufficient ? deltaPts : null,
  });

  it("looks up pre-assigned Python diverging bands and falls back to thin", () => {
    expect(bandMetaById(0, SAMPLE_BANDS, SAMPLE_THIN).label).toBe("Critical");
    expect(bandMetaById(4, SAMPLE_BANDS, SAMPLE_THIN).label).toBe("Reliable");
    expect(bandMetaById(-1, SAMPLE_BANDS, SAMPLE_THIN).label).toBe("Under 10 arrivals");
  });

  it("formats stop and grid tooltips with HTML escaping and pre-computed median delta", () => {
    const text = stopTooltip(
      { ...stop(1, 0.25, 300, true, 0, "-20.5"), label: "A & <B> (S1)" },
      10,
      "bus",
      SAMPLE_BANDS,
      SAMPLE_THIN,
      "45.5 %",
    );
    expect(text).toContain("A &amp; &lt;B&gt;");
    expect(text).toContain("Stop S1");
    expect(text).toContain("Critical");
    expect(text).toContain("-20.5 pts vs bus stop median (45.5 %)");
    expect(text).toContain("300 arrivals observed, all routes, both days");
    expect(stopTooltip(stop(3, 0.4, 4, false), 10, "bus", SAMPLE_BANDS, SAMPLE_THIN, "45.5 %")).toContain(
      "Too few arrivals to score (fewer than 10)",
    );

    const gridText = gridTooltip(
      [-73.97, 40.75, 400, 0.25, 6, 6, "5 AV & E 72", "M4", 0, "-20.5"],
      SAMPLE_BANDS,
      SAMPLE_THIN,
      "45.5 %",
      "sans-serif",
    );
    expect(gridText).toContain("5 AV &amp; E 72");
    expect(gridText).toContain("-20.5 pts vs bus stop median (45.5 %)");
  });
});

type Series = { type: string; data: { value: number[] }[] | number[][] };

describe("chart options only map exported fields to marks", () => {
  const cells = [
    {
      route_id: "B1",
      service_hour: 7,
      hour_label: "07:00",
      hour_short: "07",
      events: 40,
      on_time_share: 0.5,
      late_share: 0.4,
      median_delay_s: 120,
      scored: true,
    },
    {
      route_id: "B1",
      service_hour: 24,
      hour_label: "00:00 (+1)",
      hour_short: "00+1",
      events: 3,
      on_time_share: 1,
      late_share: 0,
      median_delay_s: 10,
      scored: false,
    },
    {
      route_id: "M15",
      service_hour: 7,
      hour_label: "07:00",
      hour_short: "07",
      events: 55,
      on_time_share: 0.8,
      late_share: 0.1,
      median_delay_s: 30,
      scored: true,
    },
  ];

  it("heatmap keeps the exported route order, hour labels and splits scored from thin cells", () => {
    const option = heatmapOption(cells, ["M15", "B1"], "mono") as {
      xAxis: { data: string[] };
      yAxis: { data: string[] };
      series: Series[];
    };
    expect(option.xAxis.data).toEqual(["07", "00+1"]);
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
        { label: "07", value: 0.5, low: 0.3, high: 0.7, thin: false, events: 20, p50: 60, p90: 200 },
        { label: "00+1", value: 1, low: 0.2, high: 1, thin: true, events: 2, p50: 0, p90: 10 },
      ],
      "mono",
    ) as { series: { data: { itemStyle: { color: string } }[] }[] };
    const dots = option.series[1].data;
    expect(dots[0].itemStyle.color).not.toBe(dots[1].itemStyle.color);
  });
});
