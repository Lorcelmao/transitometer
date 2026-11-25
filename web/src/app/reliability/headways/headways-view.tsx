"use client";

import { ModeDayView } from "@/components/site/mode-day-view";
import { BarList } from "@/components/story/bar-list";
import { ChartFrame, DataTable } from "@/components/story/chart-frame";
import { KpiRow, type KpiExtra } from "@/components/story/kpi-figure";
import { HeadwayCompositionStrip } from "@/components/story/micro-viz";
import { Definitions } from "@/components/story/page-parts";
import { headways, type Headways, type Meta } from "@/data/schemas";
import type { Initial } from "@/hooks/use-view";
import { count, dayLabel, pct } from "@/lib/format";

function Body({ data, source, day }: { data: Headways; source: Initial<Headways>["source"]; day: string }) {
  if (!data.summary) {
    return (
      <p className="my-6 rounded-xl border border-rule bg-surface p-5 text-sm text-muted-ink">
        No headways were observed on this day.
      </p>
    );
  }
  const byKey = Object.fromEntries(data.figures.map((f) => [f.key, f]));
  const regular = Number(byKey.regular?.value ?? 0);
  const bunched = Number(byKey.bunched?.value ?? 0);
  const gaps = Number(byKey.gaps?.value ?? 0);
  const irregular = Number(byKey.irregular?.value ?? 0);

  const extras: Record<string, KpiExtra> = {
    headways: { shortNote: "Total consecutive vehicle intervals observed." },
    regular: {
      badge: { label: "On rhythm", tone: "pass" },
      shortNote: "Within 20 % of the scheduled headway.",
    },
    bunched: {
      badge: bunched >= 0.05 ? { label: "Watch", tone: "attention" } : { label: "Low", tone: "pass" },
      shortNote: "At most 25 % of scheduled headway (clumping).",
    },
    gaps: {
      badge: gaps >= 0.05 ? { label: "Watch", tone: "fail" } : { label: "Low", tone: "pass" },
      shortNote: "At least double the scheduled wait time.",
    },
    irregular: {
      badge: { label: "Off rhythm", tone: "neutral" },
      shortNote: "Outside regular band, not bunched or a gap.",
    },
  };

  return (
    <div className="space-y-5">
      <p
        className="rounded-lg border border-blue-200 border-l-4 border-l-brand bg-brand-soft px-4 py-3 text-[15px] leading-relaxed text-ink"
        data-testid="headline"
      >
        <strong className="font-semibold">Day takeaway ({dayLabel(day)}):</strong>{" "}
        <span className="num font-semibold">{byKey.regular?.display}</span> of{" "}
        <span className="num">{byKey.headways?.display}</span> observed headways kept to the timetable, while{" "}
        <span className="num font-semibold">{byKey.bunched?.display}</span> bunched together and{" "}
        <span className="num font-semibold">{byKey.gaps?.display}</span> left long gaps.
      </p>

      <HeadwayCompositionStrip regular={regular} irregular={irregular} bunched={bunched} gaps={gaps} />

      <KpiRow figures={data.figures} size="md" extras={extras} />

      {data.routes.length ? (
        <ChartFrame
          title="Routes with the most bunching"
          summary={`The ${data.routes.length} routes with the highest share of bunched headways on this day (vehicles at most a quarter of the scheduled headway apart).`}
          chart={
            <BarList
              label="Share of headways bunched, by route"
              scaleMax={Math.max(...data.routes.map((r) => r.bunched_share))}
              rows={data.routes.map((r) => ({
                key: r.route_id,
                label: r.route_id,
                share: r.bunched_share,
                display: pct(r.bunched_share),
                detail: `${count(r.headways)} headways`,
              }))}
            />
          }
          table={
            <DataTable
              caption="Routes with the most bunching"
              rows={data.routes}
              rowKey={(r) => r.route_id}
              columns={[
                { key: "route", label: "Route", render: (r) => r.route_id },
                { key: "headways", label: "Headways", numeric: true, render: (r) => count(r.headways) },
                { key: "bunched", label: "Bunched", numeric: true, render: (r) => count(r.bunched) },
                { key: "gaps", label: "Gaps", numeric: true, render: (r) => count(r.gaps) },
                { key: "bunched_share", label: "Bunched share", numeric: true, render: (r) => pct(r.bunched_share) },
                { key: "regular_share", label: "Regular share", numeric: true, render: (r) => pct(r.regular_share) },
              ]}
            />
          }
          source={source}
        />
      ) : null}
      <Definitions text={data.definitions} />
    </div>
  );
}

export function HeadwaysView({ meta, initial }: { meta: Meta; initial: Initial<Headways> }) {
  return (
    <ModeDayView<Headways>
      meta={meta}
      page="headways"
      schema={headways}
      initial={initial}
      render={({ data, source, day }) => <Body data={data} source={source} day={day} />}
    />
  );
}
