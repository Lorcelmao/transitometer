/** Chart colours, mirroring the CSS tokens in app/globals.css (ECharts needs literal values). */
export const COLORS = {
  paper: "#f6f7fb",
  panel: "#eceff5",
  ink: "#161513",
  muted: "#5c564d",
  rule: "#cdd3de",
  accent: "#b3261e",
  link: "#1f4e8c",
  thin: "#aab2c0",
  sequential: ["#d6e2ee", "#9fbcd9", "#4a7fb5", "#1f4e8c", "#0b2f5b"],
} as const;

/** Shared axis styling: hairlines, muted mono labels. */
export function axisStyle(fontFamily: string) {
  return {
    axisLine: { lineStyle: { color: COLORS.rule } },
    axisTick: { show: false },
    axisLabel: { color: COLORS.muted, fontFamily, fontSize: 11 },
    splitLine: { lineStyle: { color: COLORS.rule, opacity: 0.5 } },
    nameTextStyle: { color: COLORS.muted, fontFamily, fontSize: 11 },
  };
}
