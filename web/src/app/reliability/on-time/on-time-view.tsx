"use client";

import { useCallback } from "react";

import { EChart } from "@/charts/echart";
import { heatmapOption } from "@/charts/options";
import { ModeDayView } from "@/components/site/mode-day-view";
import { BarList } from "@/components/story/bar-list";
import { ChartFrame, DataTable } from "@/components/story/chart-frame";
import { Definitions } from "@/components/story/page-parts";
import { onTime, type Meta, type OnTime } from "@/data/schemas";
import type { Initial } from "@/hooks/use-view";
import { count, dayLabel, pct } from "@/lib/format";

function Body({ data, source, day, groupLabel }: { data: OnTime; source: Initial<OnTime>["source"]; day: string; groupLabel: string }) {
  const routes = data.routes.map((r) => r.route_id);
  const build = useCallback((font: string) => heatmapOption(data.cells, routes, font), [data, routes]);
  if (!data.routes.length) {
    return <p className="my-10">No route had enough observed arrivals on this day.</p>;
  }
  const worst = data.ranking[0];
  return (
    <>
      <ChartFrame
        title={`The ${routes.length} least punctual routes, hour by hour`}
        lead={
          <p>
            On {dayLabel(day)}, route <strong>{worst.route_id}</strong> was the least punctual of the{" "}
            {groupLabel} routes: <span className="num">{pct(worst.on_time_share)}</span> of its{" "}
            <span className="num">{count(worst.events)}</span> observed arrivals were on time.
          </p>
        }
        summary={`Heatmap of on-time share by route and hour for the ${routes.length} least punctual routes, least punctual first. Darker blue means more punctual; outlined cells had fewer than ${data.min_events} arrivals and are not scored. Hours past 23 belong to the same service day after midnight.`}
        chart={<EChart build={build} height={Math.max(320, 26 * routes.length + 100)} label="On-time share by route and hour" />}
        table={
          <DataTable
            caption="On-time share by route and hour"
            rows={data.cells}
            rowKey={(c) => `${c.route_id}-${c.service_hour}`}
            columns={[
              { key: "route", label: "Route", render: (c) => c.route_id },
              { key: "hour", label: "Hour", numeric: true, render: (c) => c.service_hour },
              { key: "events", label: "Arrivals", numeric: true, render: (c) => count(c.events) },
              { key: "on_time", label: "On time", numeric: true, render: (c) => (c.scored ? pct(c.on_time_share) : `${pct(c.on_time_share)} (not scored)`) },
              { key: "late", label: "Late", numeric: true, render: (c) => pct(c.late_share) },
            ]}
          />
        }
        source={source}
      />
      <ChartFrame
        title="Least punctual routes over the whole day"
        summary={`The ${data.ranking.length} routes with the lowest share of on-time arrivals on this day, weighted by arrivals, counting only route-hours with at least ${data.min_events} arrivals.`}
        chart={
          <BarList
            label="Share of arrivals on time, by route"
            rows={data.ranking.map((r) => ({
              key: r.route_id,
              label: r.route_id,
              share: r.on_time_share,
              display: pct(r.on_time_share),
              detail: `${count(r.events)} arrivals`,
            }))}
          />
        }
        table={
          <DataTable
            caption="Least punctual routes"
            rows={data.routes}
            rowKey={(r) => r.route_id}
            columns={[
              { key: "route", label: "Route", render: (r) => r.route_id },
              { key: "events", label: "Arrivals", numeric: true, render: (r) => count(r.events) },
              { key: "on_time", label: "On time", numeric: true, render: (r) => pct(r.on_time_share) },
              { key: "late", label: "Late", numeric: true, render: (r) => pct(r.late_share) },
            ]}
          />
        }
        source={source}
      />
      <Definitions text={data.definitions} />
    </>
  );
}

export function OnTimeView({ meta, initial }: { meta: Meta; initial: Initial<OnTime> }) {
  return (
    <ModeDayView<OnTime>
      meta={meta}
      page="on-time"
      schema={onTime}
      initial={initial}
      render={({ data, source, mode, day }) => (
        <Body data={data} source={source} day={day} groupLabel={meta.modes.find((m) => m.key === mode)?.label ?? mode} />
      )}
    />
  );
}
