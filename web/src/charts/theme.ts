/** Chart colours, mirroring the CSS tokens in app/globals.css (ECharts needs literal values). */
export const COLORS = {
  paper: "#f6f7fb",
  surface: "#ffffff",
  panel: "#eff2f8",
  ink: "#0f172a",
  muted: "#475569",
  rule: "#dce2ec",
  accent: "#b3261e",
  attention: "#b45309",
  pass: "#1e6130",
  link: "#1f4e8c",
  thin: "#94a3b8",
  sequential: ["#d6e2ee", "#9fbcd9", "#4a7fb5", "#1f4e8c", "#0b2f5b"],
  /** Stop map basemap & WCAG AA diverging scale (>= 4.1:1 on #f4f6f9 land, >= 4.5:1 on white). */
  mapWater: "#dde9f5",
  mapLand: "#f4f6f9",
  mapShoreline: "#8ea4bc",
  mapStreets: "#c2cedc",
  mapSubway: "#8ba0b8",
  mapThinStroke: "#475569",
  mapDiverging: ["#b3261e", "#c2570a", "#64748b", "#2b6cb0", "#0b3b75"],
} as const;

/** Shared axis styling: crisp hairlines and legible 12 px labels. */
export function axisStyle(fontFamily: string) {
  return {
    axisLine: { lineStyle: { color: COLORS.rule } },
    axisTick: { show: false },
    axisLabel: { color: COLORS.muted, fontFamily, fontSize: 12 },
    splitLine: { lineStyle: { color: COLORS.rule, opacity: 0.6 } },
    nameTextStyle: { color: COLORS.muted, fontFamily, fontSize: 12 },
  };
}
