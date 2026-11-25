import type { Overview } from "@/data/schemas";
import { count, serviceHour } from "@/lib/format";

type Hour = Overview["views"][string]["hours"][number];

/**
 * On-time share by hour of the service day as a plain SVG chart (no chart library on the overview).
 * Marks the daily high (blue circle) and daily low (amber diamond) among sufficient hours,
 * draws hollow circles for low-volume hours, and labels hours past midnight as 00:00 (+1), etc.
 */
export function HourlyProfile({ hours, label }: { hours: Hour[]; label: string }) {
  const W = 640;
  const H = 236;
  const pad = { left: 48, right: 44, top: 20, bottom: 32 };
  const maxHour = Math.max(23, ...hours.map((h) => h.service_hour));
  const x = (hour: number) => pad.left + (hour / maxHour) * (W - pad.left - pad.right);
  const y = (share: number) => pad.top + (1 - share) * (H - pad.top - pad.bottom);

  const points = hours.filter((h) => h.on_time_share !== null);
  const sufficient = points.filter((h) => h.sufficient);
  const lowPt = sufficient.length
    ? sufficient.reduce((a, b) => ((b.on_time_share as number) < (a.on_time_share as number) ? b : a), sufficient[0])
    : null;
  const highPt = sufficient.length
    ? sufficient.reduce((a, b) => ((b.on_time_share as number) > (a.on_time_share as number) ? b : a), sufficient[0])
    : null;

  const path = points
    .map((h, i) => `${i ? "L" : "M"}${x(h.service_hour).toFixed(1)},${y(h.on_time_share as number).toFixed(1)}`)
    .join("");
  const area = points.length
    ? `${path}L${x(points[points.length - 1].service_hour).toFixed(1)},${y(0)}L${x(points[0].service_hour).toFixed(1)},${y(0)}Z`
    : "";

  const ticks = Array.from({ length: Math.floor(maxHour / 4) + 1 }, (_, i) => i * 4);
  const clampLabelX = (cx: number) => Math.max(pad.left + 58, Math.min(W - pad.right - 58, cx));

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label={label}
      className="h-auto w-full"
      data-testid="hourly-profile"
    >
      {[0, 0.25, 0.5, 0.75, 1].map((v) => (
        <g key={v}>
          <line
            x1={pad.left}
            x2={W - pad.right}
            y1={y(v)}
            y2={y(v)}
            stroke="var(--rule)"
            strokeWidth={v === 0 ? 1.2 : 0.75}
          />
          <text x={pad.left - 8} y={y(v) + 4} textAnchor="end" className="fill-muted-ink text-[12px]">
            {v * 100} %
          </text>
        </g>
      ))}
      {ticks.map((hour) => (
        <text key={hour} x={x(hour)} y={H - 8} textAnchor="middle" className="fill-muted-ink text-[12px]">
          {hour >= 24 ? `${String(hour - 24).padStart(2, "0")}:00 (+1)` : `${String(hour).padStart(2, "0")}:00`}
        </text>
      ))}
      <path d={area} fill="var(--seq-1)" opacity={0.5} />
      <path d={path} fill="none" stroke="var(--seq-4)" strokeWidth={2.2} strokeLinejoin="round" />

      {points.map((h) => {
        const cx = x(h.service_hour);
        const cy = y(h.on_time_share as number);
        const hLabel = serviceHour(h.service_hour);
        const isLow = lowPt && h.service_hour === lowPt.service_hour;
        const isHigh = highPt && h.service_hour === highPt.service_hour;
        if (isLow) {
          return (
            <g key={h.service_hour}>
              <rect
                x={cx - 4.5}
                y={cy - 4.5}
                width={9}
                height={9}
                transform={`rotate(45 ${cx.toFixed(1)} ${cy.toFixed(1)})`}
                fill="var(--attention)"
                stroke="var(--surface)"
                strokeWidth={1.5}
              >
                <title>{`${hLabel} (daily low): ${h.display} on time, ${count(h.events)} arrivals`}</title>
              </rect>
              <text
                x={clampLabelX(cx)}
                y={Math.min(y(0) - 8, cy + 19)}
                textAnchor="middle"
                className="fill-attention-text text-[12px] font-semibold"
              >
                {`Low ${h.display} (${hLabel})`}
              </text>
            </g>
          );
        }
        if (isHigh) {
          return (
            <g key={h.service_hour}>
              <circle cx={cx} cy={cy} r={5} fill="var(--seq-4)" stroke="var(--surface)" strokeWidth={1.6}>
                <title>{`${hLabel} (daily high): ${h.display} on time, ${count(h.events)} arrivals`}</title>
              </circle>
              <text
                x={clampLabelX(cx)}
                y={Math.max(pad.top + 10, cy - 10)}
                textAnchor="middle"
                className="fill-brand text-[12px] font-semibold"
              >
                {`High ${h.display} (${hLabel})`}
              </text>
            </g>
          );
        }
        return (
          <circle
            key={h.service_hour}
            cx={cx}
            cy={cy}
            r={h.sufficient ? 3.5 : 3}
            fill={h.sufficient ? "var(--seq-4)" : "var(--surface)"}
            stroke={h.sufficient ? "var(--surface)" : "var(--seq-3)"}
            strokeWidth={1.4}
          >
            <title>{`${hLabel}: ${h.display} on time, ${count(h.events)} arrivals${h.sufficient ? "" : " (few arrivals)"}`}</title>
          </circle>
        );
      })}
    </svg>
  );
}
