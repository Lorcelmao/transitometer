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
