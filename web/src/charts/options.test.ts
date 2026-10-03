import { describe, expect, it } from "vitest";

import { heatmapOption, hourlyIntervalOption, routeIntervalOption } from "@/charts/options";

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
