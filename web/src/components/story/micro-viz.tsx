/**
 * Compact, real-data micro-visuals for dashboard KPI cards, Key Findings, Feed Health, and Headways.
 * Zero client charting dependency: plain HTML/SVG driven directly by exported Python JSON values.
 */
import { pct } from "@/lib/format";

function clampPct(v: number): number {
  return Math.max(0, Math.min(100, v * 100));
}

/**
 * 0 to 100 % comparison bar showing the active mode's value against the peer mode on the same day
 * (with explicit day scope printed right beside the peer figure).
 */
export function PeerCompareBar({
  value,
  peerValue,
  peerLabel,
  peerDisplay,
  fillTone = "brand",
  leftLabel = "0 %",
  rightLabel,
}: {
  value: number;
  peerValue: number;
  peerLabel: string;
  peerDisplay: string;
  fillTone?: "brand" | "attention" | "fail";
  leftLabel?: string;
  rightLabel?: string;
}) {
  const fillClass =
    fillTone === "fail" ? "bg-fail" : fillTone === "attention" ? "bg-attention" : "bg-brand";
  const markerClass = fillTone === "brand" ? "bg-attention" : "bg-brand";
  const peerTextClass = fillTone === "brand" ? "text-attention-text" : "text-brand";
  const fillW = Math.max(1.5, clampPct(value));
  const markerLeft = Math.max(1.5, Math.min(98.5, clampPct(peerValue)));

  return (
    <div className="space-y-1.5">
      <div className="relative h-2 rounded-full bg-panel" aria-hidden="true">
        <div className={`h-full rounded-full ${fillClass}`} style={{ width: `${fillW.toFixed(1)}%` }} />
        <div
          className={`absolute -top-[3px] h-3.5 w-[2.5px] -translate-x-1/2 rounded-xs ${markerClass}`}
          style={{ left: `${markerLeft.toFixed(1)}%` }}
        />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-0.5 text-xs text-muted-ink">
        <span>{rightLabel ? `${leftLabel.replace(" %", "")} to ${rightLabel}` : leftLabel}</span>
        <span className={`num font-semibold ${peerTextClass}`}>
          {peerLabel}: {peerDisplay}
        </span>
      </div>
    </div>
  );
}

/** Discrete pass/fail check blocks (green left, red right), matching Feed Health cards. */
export function CheckStrip({ passed, total }: { passed: number; total: number }) {
  const failed = Math.max(0, total - passed);
  return (
    <div className="space-y-1.5">
      <div
        className="grid gap-1"
        style={{ gridTemplateColumns: `repeat(${Math.max(1, total)}, minmax(0, 1fr))` }}
        aria-hidden="true"
      >
        {Array.from({ length: total }, (_, i) => (
          <span
            key={i}
            className={`h-2.5 rounded-xs ${i < passed ? "bg-pass" : "bg-fail"}`}
          />
        ))}
      </div>
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="num font-semibold text-pass-text">
          {passed} of {total} checks passed
        </span>
        <span className={`num font-semibold ${failed ? "text-fail-text" : "text-pass-text"}`}>
          {failed ? `${failed} failed` : "No failures"}
        </span>
      </div>
    </div>
  );
}

/** Bullet bar comparing a measured feed-health metric against its upper limit (dark tick). */
export function ThresholdBullet({
  value,
  threshold,
  passed,
  measured,
  thresholdDisplay,
}: {
  value: number | null;
  threshold: number;
  passed: boolean;
  measured: string;
  thresholdDisplay: string;
}) {
  const safeVal = value ?? 0;
  // Scale so threshold always sits around 35% to 55% of the track unless measured far exceeds it
  const maxScale = Math.max(threshold * 2.5, safeVal * 1.15, 1e-6);
  const valPct = value === null ? 0 : Math.min(100, Math.max(safeVal > 0 ? 2.5 : 0, (safeVal / maxScale) * 100));
  const tickPct = Math.min(96, Math.max(6, (threshold / maxScale) * 100));

  return (
    <div className="min-w-[155px] space-y-1">
      <div className="relative h-2.5 rounded-full bg-panel" aria-hidden="true">
        {valPct > 0 ? (
          <div
            className={`h-full rounded-full ${passed ? "bg-pass" : "bg-fail"}`}
            style={{ width: `${valPct.toFixed(1)}%` }}
          />
        ) : null}
        <div
          className="absolute -top-1 h-4 w-[2px] -translate-x-1/2 bg-ink"
          style={{ left: `${tickPct.toFixed(1)}%` }}
        />
      </div>
      <p className="num text-xs text-muted-ink">
        Measured {measured} vs limit {thresholdDisplay}
      </p>
    </div>
  );
}

/** 100 % 4-segment stacked strip for Headways (Regular | Irregular | Bunched | Gaps). */
export function HeadwayCompositionStrip({
  regular,
  irregular,
  bunched,
  gaps,
}: {
  regular: number;
  irregular: number;
  bunched: number;
  gaps: number;
}) {
  const segments = [
    { key: "regular", label: "Regular", value: regular, color: "bg-brand" },
    { key: "irregular", label: "Irregular", value: irregular, color: "bg-seq-2" },
    { key: "bunched", label: "Bunched", value: bunched, color: "bg-attention" },
    { key: "gaps", label: "Gaps", value: gaps, color: "bg-fail" },
  ];
  return (
    <div className="rounded-xl border border-rule bg-surface p-4 shadow-xs">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm font-semibold text-ink">Headway composition (100 % of observed headways)</p>
        <p className="text-xs text-muted-ink">Regular + irregular + bunched + long gaps</p>
      </div>
      <div
        className="mt-3 flex h-3.5 w-full overflow-hidden rounded-full bg-panel"
        role="img"
        aria-label={`Headway composition: Regular ${pct(regular)}, Irregular ${pct(irregular)}, Bunched ${pct(bunched)}, Gaps ${pct(gaps)}`}
      >
        {segments.map((s) => (
          <div
            key={s.key}
            className={s.color}
            style={{ width: `${Math.max(0, s.value * 100).toFixed(2)}%` }}
            title={`${s.label}: ${pct(s.value)}`}
          />
        ))}
      </div>
      <div className="mt-2.5 flex flex-wrap gap-x-5 gap-y-1.5 text-xs text-muted-ink">
        {segments.map((s) => (
          <span key={s.key} className="inline-flex items-center gap-1.5">
            <span className={`inline-block size-2.5 rounded-full ${s.color}`} aria-hidden="true" />
            <span className="font-medium text-ink">{s.label}</span>
            <span className="num">{pct(s.value)}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

/** Mini horizontal bars used inside Overview Finding cards (with optional threshold tick). */
export function MiniComparisonBars({
  rows,
}: {
  rows: {
    label: string;
    value: number;
    display: string;
    tone: "brand" | "attention" | "muted" | "pass";
    threshold?: number;
    thresholdLabel?: string;
  }[];
}) {
  const colorMap = {
    brand: "bg-seq-4",
    attention: "bg-attention",
    muted: "bg-slate-400",
    pass: "bg-pass",
  };
  return (
    <div className="flex flex-col gap-2">
      {rows.map((r) => (
        <div key={r.label} className="grid grid-cols-[76px_1fr_54px] items-center gap-2 text-xs">
          <span className="font-semibold text-ink">{r.label}</span>
          <div className="relative h-2.5 rounded-full bg-slate-200" aria-hidden="true">
            <div
              className={`h-full rounded-full ${colorMap[r.tone]}`}
              style={{ width: `${clampPct(r.value).toFixed(1)}%` }}
            />
            {r.threshold !== undefined ? (
              <div
                className="absolute -top-[3px] -bottom-[3px] w-[2px] bg-ink"
                style={{ left: `${clampPct(r.threshold).toFixed(1)}%` }}
                title={r.thresholdLabel}
              />
            ) : null}
          </div>
          <span className="num text-right font-semibold text-ink">{r.display}</span>
        </div>
      ))}
    </div>
  );
}

/** Compact 24-hour pooled bus curve for Overview Finding 2 (marks peak high and afternoon low). */
export function MiniHourlySparkline({
  points,
  lowHour,
  highHour,
}: {
  points: { hour: number; share: number }[];
  lowHour: { hour: number; share: number; display: string };
  highHour: { hour: number; share: number; display: string };
}) {
  const W = 360;
  const H = 92;
  const padL = 12;
  const padR = 12;
  const topY = 26;
  const botY = 72;
  const x = (h: number) => padL + (h / 23) * (W - padL - padR);
  const y = (s: number) => botY - s * (botY - topY);

  const lineD = points.map((p, i) => `${i ? "L" : "M"}${x(p.hour).toFixed(1)},${y(p.share).toFixed(1)}`).join(" ");
  const areaD = points.length
    ? `${lineD} L${x(points[points.length - 1].hour).toFixed(1)},${botY} L${x(points[0].hour).toFixed(1)},${botY} Z`
    : "";

  const lx = x(lowHour.hour);
  const ly = y(lowHour.share);
  const hx = x(highHour.hour);
  const hy = y(highHour.share);

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="h-[92px] w-full"
      role="img"
      aria-label={`24-hour pooled bus punctuality curve peaking at ${String(highHour.hour).padStart(2, "0")}:00 (${highHour.display}) and dipping to ${lowHour.display} at ${String(lowHour.hour).padStart(2, "0")}:00`}
    >
      <line x1={padL} x2={W - padR} y1={y(0.5)} y2={y(0.5)} stroke="var(--rule)" strokeDasharray="3 3" strokeWidth={1} />
      <line x1={padL} x2={W - padR} y1={botY} y2={botY} stroke="var(--rule-strong)" strokeWidth={1} />
      <path d={areaD} fill="var(--seq-1)" opacity={0.45} />
      <path d={lineD} fill="none" stroke="var(--brand)" strokeWidth={2} strokeLinejoin="round" />
      <line x1={lx} x2={lx} y1={ly} y2={botY} stroke="var(--attention)" strokeDasharray="2 2" strokeWidth={1.2} />
      <circle cx={hx} cy={hy} r={4.2} fill="var(--brand)" stroke="var(--surface)" strokeWidth={1.5} />
      <rect
        x={lx - 4}
        y={ly - 4}
        width={8}
        height={8}
        transform={`rotate(45 ${lx.toFixed(1)} ${ly.toFixed(1)})`}
        fill="var(--attention)"
        stroke="var(--surface)"
        strokeWidth={1.4}
      />
      <text
        x={Math.max(padL, Math.min(W - 120, hx))}
        y={16}
        className="fill-brand text-[12px] font-semibold"
      >
        {`${String(highHour.hour).padStart(2, "0")}:00 high (${highHour.display})`}
      </text>
      <text
        x={Math.max(70, Math.min(W - 70, lx))}
        y={Math.max(16, ly - 10)}
        textAnchor="middle"
        className="fill-attention-text text-[12px] font-semibold"
      >
        {`${String(lowHour.hour).padStart(2, "0")}:00 low (${lowHour.display})`}
      </text>
      <text x={padL} y={H - 4} className="fill-muted-ink text-[12px]">
        00:00
      </text>
      <text x={x(8)} y={H - 4} textAnchor="middle" className="fill-muted-ink text-[12px]">
        08:00
      </text>
      <text x={lx} y={H - 4} textAnchor="middle" className="fill-attention-text text-[12px] font-semibold">
        {`${String(lowHour.hour).padStart(2, "0")}:00`}
      </text>
      <text x={W - padR} y={H - 4} textAnchor="end" className="fill-muted-ink text-[12px]">
        23:00
      </text>
    </svg>
  );
}

/** 0 to 100 % confidence interval plot comparing one route against the bus route median and IQR. */
export function MiniIntervalPlot({
  routeId,
  value,
  ciLow,
  ciHigh,
  median,
  q25,
  q75,
}: {
  routeId: string;
  value: number;
  ciLow: number;
  ciHigh: number;
  median: number;
  q25: number;
  q75: number;
}) {
  const W = 340;
  const H = 78;
  const x = (s: number) => 12 + Math.max(0, Math.min(1, s)) * (W - 24);
  const cx = x(value);
  const lx = x(ciLow);
  const hx = x(ciHigh);
  const mx = x(median);
  const q1x = x(q25);
  const q3x = x(q75);

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="h-[78px] w-full"
      role="img"
      aria-label={`${routeId} on-time share ${pct(value)} with 95 % interval ${pct(ciLow)} to ${pct(ciHigh)}, compared against bus route median ${pct(median)} (middle half ${pct(q25)} to ${pct(q75)})`}
    >
      <rect x={12} y={32} width={W - 24} height={8} rx={4} fill="var(--panel)" />
      <rect x={q1x} y={29} width={Math.max(4, q3x - q1x)} height={14} rx={3} fill="var(--seq-1)" />
      <line x1={mx} x2={mx} y1={23} y2={49} stroke="var(--brand)" strokeWidth={2} />
      <line x1={lx} x2={hx} y1={36} y2={36} stroke="var(--fail)" strokeWidth={3} strokeLinecap="round" />
      <line x1={lx} x2={lx} y1={31} y2={41} stroke="var(--fail)" strokeWidth={1.8} />
      <line x1={hx} x2={hx} y1={31} y2={41} stroke="var(--fail)" strokeWidth={1.8} />
      <circle cx={cx} cy={36} r={5} fill="var(--fail)" stroke="var(--surface)" strokeWidth={1.5} />
      <text x={Math.max(66, cx)} y={16} textAnchor="middle" className="fill-fail-text text-[12px] font-semibold">
        {`${routeId} (${pct(ciLow)} to ${pct(ciHigh)})`}
      </text>
      <text x={Math.min(W - 12, mx + 5)} y={16} textAnchor="start" className="fill-brand text-[12px] font-semibold">
        {`Median ${pct(median)}`}
      </text>
      <text x={12} y={H - 6} className="fill-muted-ink text-[12px]">
        0 %
      </text>
      <text x={W / 2} y={H - 6} textAnchor="middle" className="fill-muted-ink text-[12px]">
        50 % (shaded: middle half)
      </text>
      <text x={W - 12} y={H - 6} textAnchor="end" className="fill-muted-ink text-[12px]">
        100 %
      </text>
    </svg>
  );
}
