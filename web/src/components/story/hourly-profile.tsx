import type { Overview } from "@/data/schemas";
import { count } from "@/lib/format";

type Hour = Overview["views"][string]["hours"][number];

/**
 * On-time share by hour of the service day as a plain SVG line (no chart library on the
 * overview). Hours with fewer arrivals than the export's threshold are drawn hollow and lighter:
 * shown, not compared. Values and their display strings come from the Python views.
 */
export function HourlyProfile({ hours, label }: { hours: Hour[]; label: string }) {
  const W = 640;
  const H = 220;
  const pad = { left: 40, right: 12, top: 12, bottom: 28 };
  const maxHour = Math.max(23, ...hours.map((h) => h.service_hour));
  const x = (hour: number) => pad.left + (hour / maxHour) * (W - pad.left - pad.right);
  const y = (share: number) => pad.top + (1 - share) * (H - pad.top - pad.bottom);
  const points = hours.filter((h) => h.on_time_share !== null);
  const path = points.map((h, i) => `${i ? "L" : "M"}${x(h.service_hour).toFixed(1)},${y(h.on_time_share as number).toFixed(1)}`).join("");
  const area = points.length
    ? `${path}L${x(points[points.length - 1].service_hour).toFixed(1)},${y(0)}L${x(points[0].service_hour).toFixed(1)},${y(0)}Z`
    : "";
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} className="h-auto w-full" data-testid="hourly-profile">
      {[0, 0.25, 0.5, 0.75, 1].map((v) => (
        <g key={v}>
          <line x1={pad.left} x2={W - pad.right} y1={y(v)} y2={y(v)} stroke="var(--rule)" strokeWidth={v === 0 ? 1 : 0.6} />
          <text x={pad.left - 6} y={y(v) + 3} textAnchor="end" className="fill-muted-ink font-mono text-[10px]">
            {v * 100} %
          </text>
        </g>
      ))}
      {Array.from({ length: Math.floor(maxHour / 3) + 1 }, (_, i) => i * 3).map((hour) => (
        <text key={hour} x={x(hour)} y={H - 8} textAnchor="middle" className="fill-muted-ink font-mono text-[10px]">
          {String(hour).padStart(2, "0")}
        </text>
      ))}
      <path d={area} fill="var(--seq-1)" opacity={0.55} />
      <path d={path} fill="none" stroke="var(--seq-4)" strokeWidth={2} strokeLinejoin="round" />
      {points.map((h) => (
        <circle
          key={h.service_hour}
          cx={x(h.service_hour)}
          cy={y(h.on_time_share as number)}
          r={h.sufficient ? 3.2 : 2.6}
          fill={h.sufficient ? "var(--seq-4)" : "var(--paper)"}
          stroke={h.sufficient ? "var(--paper)" : "var(--seq-3)"}
          strokeWidth={1.2}
        >
          <title>{`${String(h.service_hour).padStart(2, "0")}:00 · ${h.display} on time · ${count(h.events)} arrivals${h.sufficient ? "" : " (few arrivals)"}`}</title>
        </circle>
      ))}
    </svg>
  );
}
