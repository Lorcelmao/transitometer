"use client";

/**
 * A lazily loaded ECharts chart. The container reserves its height (no layout shift); the chart
 * library is downloaded only when a chart nears the viewport. Animation is off when the visitor
 * prefers reduced motion. Every chart on the site also has a text summary and a table view
 * (ChartFrame), so the data never depends on seeing or hovering the chart.
 */
import type { EChartsCoreOption, EChartsType } from "echarts/core";
import { useEffect, useRef } from "react";

export type BuildOption = (fontFamily: string) => EChartsCoreOption;

export function EChart({
  build,
  height,
  aspectRatio,
  label,
  renderer = "svg",
  onPointClick,
}: {
  build: BuildOption;
  /** Fixed height in pixels, or a CSS aspect ratio (for example "1 / 1") instead. */
  height?: number;
  aspectRatio?: string;
  label: string;
  renderer?: "svg" | "canvas";
  /** Called with the clicked data item (the object passed in the series data). */
  onPointClick?: (item: unknown) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const chart = useRef<EChartsType | null>(null);
  const latest = useRef(build);

  function apply(instance: EChartsType, builder: BuildOption) {
    const font =
      getComputedStyle(document.documentElement).getPropertyValue("--font-plex-mono").trim() ||
      "monospace";
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    instance.setOption(
      {
        ...builder(font),
        animation: !reduced,
        animationDuration: 200,
        aria: { enabled: true, label: { description: label } },
        textStyle: { fontFamily: font },
      },
      { notMerge: true },
    );
  }

  useEffect(() => {
    let disposed = false;
    let resize: ResizeObserver | undefined;
    const element = container.current;
    if (!element) return;
    // Download and draw the chart only when it is about to scroll into view.
    const visible = new IntersectionObserver(
      (entries) => {
        if (!entries.some((e) => e.isIntersecting)) return;
        visible.disconnect();
        import("@/charts/echarts-setup").then(({ echarts }) => {
          if (disposed) return;
          const instance = echarts.init(element, null, { renderer });
          chart.current = instance;
          if (onPointClick) instance.on("click", (event) => onPointClick(event.data));
          apply(instance, latest.current);
          resize = new ResizeObserver(() => instance.resize());
          resize.observe(element);
        });
      },
      { rootMargin: "200px" },
    );
    visible.observe(element);
    return () => {
      disposed = true;
      visible.disconnect();
      resize?.disconnect();
      chart.current?.dispose();
      chart.current = null;
    };
    // initialise once; option changes are applied by the effect below
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    latest.current = build;
    if (chart.current) apply(chart.current, build);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [build]);

  return (
    <div ref={container} role="img" aria-label={label} style={{ height, aspectRatio }} className="w-full" />
  );
}
