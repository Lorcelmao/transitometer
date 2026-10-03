"use client";

import { ModeDayView } from "@/components/site/mode-day-view";
import { BarList } from "@/components/story/bar-list";
import { ChartFrame, DataTable } from "@/components/story/chart-frame";
import { KpiRow } from "@/components/story/kpi-figure";
import { Definitions } from "@/components/story/page-parts";
import { headways, type Headways, type Meta } from "@/data/schemas";
import type { Initial } from "@/hooks/use-view";
import { count, dayLabel, pct } from "@/lib/format";

function Body({ data, source, day }: { data: Headways; source: Initial<Headways>["source"]; day: string }) {
  if (!data.summary) return <p className="my-10">No headways were observed on this day.</p>;
  const shares = Object.fromEntries(data.figures.map((f) => [f.key, f.display]));
  return (
    <>
      <p className="max-w-3xl font-display text-2xl leading-snug md:text-3xl" data-testid="headline">
        On {dayLabel(day)}, <span className="num">{shares.regular}</span> of the{" "}
        <span className="num">{shares.headways}</span> observed headways kept to the timetable;{" "}
        <span className="num">{shares.bunched}</span> were bunched and <span className="num">{shares.gaps}</span>{" "}
        were long gaps.
      </p>
      <div className="mt-8">
        <KpiRow figures={data.figures} size="md" />
      </div>
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
    </>
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
