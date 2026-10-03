"use client";

import { Markdown } from "@/components/markdown";
import { ModeDayView } from "@/components/site/mode-day-view";
import { BarList } from "@/components/story/bar-list";
import { ChartFrame, DataTable } from "@/components/story/chart-frame";
import { KpiRow } from "@/components/story/kpi-figure";
import { Caveat, Definitions } from "@/components/story/page-parts";
import { missingTrips, type Meta, type MissingTrips } from "@/data/schemas";
import type { Initial } from "@/hooks/use-view";
import { count, pct } from "@/lib/format";

function Body({ data, source }: { data: MissingTrips; source: Initial<MissingTrips>["source"] }) {
  if (!data.summary) return <p className="my-10">No scheduled trips on this day.</p>;
  const most = Math.max(...data.outcomes.map((o) => o.trips));
  return (
    <>
      <div className="mt-2">
        <KpiRow figures={data.figures} size="md" />
      </div>
      {data.caveat ? (
        <Caveat>
          <Markdown className="inline [&>p]:inline">{data.caveat.text}</Markdown>
        </Caveat>
      ) : null}
      <ChartFrame
        title="What happened to every scheduled trip"
        summary="Each scheduled trip gets exactly one outcome. Bars in red (missing, not run) are the trips counted as not delivered."
        chart={
          <BarList
            label="Scheduled trips by outcome"
            scaleMax={most}
            rows={data.outcomes.map((o) => ({
              key: o.key,
              label: o.outcome,
              share: o.trips,
              display: count(o.trips),
              detail: o.not_delivered ? "not delivered" : undefined,
              emphasis: o.not_delivered,
            }))}
          />
        }
        table={
          <DataTable
            caption="Scheduled trips by outcome"
            rows={data.outcomes}
            rowKey={(o) => o.key}
            columns={[
              { key: "outcome", label: "Outcome", render: (o) => o.outcome },
              { key: "trips", label: "Trips", numeric: true, render: (o) => count(o.trips) },
              { key: "counted", label: "Counted as not delivered", render: (o) => (o.not_delivered ? "Yes" : "No") },
            ]}
          />
        }
        source={source}
      />
      {data.routes.length ? (
        <ChartFrame
          title="Routes with the most undelivered trips"
          summary={`The ${data.routes.length} routes with the highest share of observable scheduled trips not delivered, among routes with at least ${data.min_trips} observable trips.`}
          chart={
            <BarList
              label="Share of observable trips not delivered, by route"
              scaleMax={Math.max(...data.routes.map((r) => r.not_delivered_share))}
              rows={data.routes.map((r) => ({
                key: r.route_id,
                label: r.route_id,
                share: r.not_delivered_share,
                display: pct(r.not_delivered_share),
                detail: `${count(r.scheduled)} scheduled`,
              }))}
            />
          }
          table={
            <DataTable
              caption="Routes with the most undelivered trips"
              rows={data.routes}
              rowKey={(r) => r.route_id}
              columns={[
                { key: "route", label: "Route", render: (r) => r.route_id },
                { key: "scheduled", label: "Scheduled", numeric: true, render: (r) => count(r.scheduled) },
                { key: "missing", label: "Missing", numeric: true, render: (r) => count(r.missing) },
                { key: "not_run", label: "Not run", numeric: true, render: (r) => count(r.not_run) },
                { key: "unknown", label: "Unknown", numeric: true, render: (r) => count(r.unknown) },
                { key: "share", label: "Not delivered", numeric: true, render: (r) => pct(r.not_delivered_share) },
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

export function MissingTripsView({ meta, initial }: { meta: Meta; initial: Initial<MissingTrips> }) {
  return (
    <ModeDayView<MissingTrips>
      meta={meta}
      page="missing-trips"
      schema={missingTrips}
      initial={initial}
      render={({ data, source }) => <Body data={data} source={source} />}
    />
  );
}
