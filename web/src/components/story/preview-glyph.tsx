import type { Preview } from "@/components/site/nav";

/**
 * A small sketch of the chart a page holds, for menus and explore cards. Decorative only
 * (aria-hidden): the page title and description carry the meaning, and the shapes are fixed, not
 * data.
 */
const INK = "var(--ink)";
const SEQ = ["var(--seq-1)", "var(--seq-2)", "var(--seq-3)", "var(--seq-4)", "var(--seq-5)"];

function shapes(kind: Preview) {
  switch (kind) {
    case "heatmap":
      return Array.from({ length: 24 }, (_, i) => (
        <rect key={i} x={4 + (i % 8) * 7} y={6 + Math.floor(i / 8) * 10} width={6} height={9} fill={SEQ[(i * 7) % 5]} />
      ));
    case "bars":
      return [44, 36, 30, 22, 16].map((w, i) => <rect key={i} x={4} y={5 + i * 7} width={w} height={4} fill={SEQ[3]} />);
    case "outcomes":
      return [52, 10, 6, 4].map((w, i) => (
        <rect key={i} x={4} y={7 + i * 8} width={w} height={5} fill={i === 2 || i === 3 ? "var(--accent-red)" : SEQ[2]} />
      ));
    case "intervals":
      return [0, 1, 2, 3].map((i) => (
        <g key={i}>
          <line x1={10 + i * 4} x2={30 + i * 6} y1={8 + i * 8} y2={8 + i * 8} stroke={SEQ[3]} strokeWidth={1.5} />
          <circle cx={20 + i * 5} cy={8 + i * 8} r={2.5} fill={SEQ[4]} />
        </g>
      ));
    case "hours":
      return [14, 22, 18, 26, 12, 20, 24].map((h, i) => (
        <g key={i}>
          <line x1={8 + i * 8} x2={8 + i * 8} y1={36 - h - 6} y2={36 - h + 6} stroke={SEQ[3]} strokeWidth={1.5} />
          <circle cx={8 + i * 8} cy={36 - h} r={2} fill={i === 4 ? "var(--paper)" : SEQ[4]} stroke={SEQ[4]} />
        </g>
      ));
    case "map":
      return [
        [30, 8], [33, 12], [28, 15], [35, 18], [31, 22], [38, 24], [42, 20], [46, 26], [24, 28], [20, 32], [14, 34], [40, 30], [50, 30], [27, 20], [36, 9],
      ].map(([x, y], i) => <circle key={i} cx={x} cy={y} r={1.8} fill={SEQ[(i * 3) % 5]} />);
    case "split":
      return [0, 1, 2].map((i) => (
        <g key={i}>
          <rect x={4} y={8 + i * 10} width={14 + i * 3} height={6} fill={SEQ[1]} />
          <rect x={18 + i * 3} y={8 + i * 10} width={20 - i * 4} height={6} fill={SEQ[4]} />
        </g>
      ));
    case "verdict":
      return (
        <g>
          <circle cx={20} cy={20} r={10} fill="none" stroke="var(--pass)" strokeWidth={2} />
          <path d="M15 20 l4 4 l7 -8" fill="none" stroke="var(--pass)" strokeWidth={2} />
          <rect x={36} y={12} width={22} height={4} fill={SEQ[3]} />
          <rect x={36} y={22} width={16} height={4} fill="var(--rule)" />
        </g>
      );
    case "checks":
      return [0, 1, 2, 3].map((i) => (
        <g key={i}>
          <circle cx={9} cy={8 + i * 8} r={2.5} fill={i === 2 ? "var(--fail)" : "var(--pass)"} />
          <rect x={15} y={7 + i * 8} width={36 - i * 4} height={2} fill={INK} opacity={0.5} />
        </g>
      ));
    case "evidence":
      return (
        <g fill="none" stroke={INK} strokeWidth={1.2} opacity={0.7}>
          <rect x={10} y={5} width={22} height={30} />
          <path d="M14 13h14M14 19h14M14 25h9" />
          <circle cx={42} cy={22} r={8} />
          <path d="M48 28l7 7" />
        </g>
      );
  }
}

export function PreviewGlyph({ kind, className = "" }: { kind: Preview; className?: string }) {
  return (
    <svg viewBox="0 0 64 40" aria-hidden="true" focusable="false" className={className}>
      {shapes(kind)}
    </svg>
  );
}
