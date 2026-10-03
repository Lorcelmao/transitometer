"use client";

import { useCallback } from "react";

import { EChart } from "@/charts/echart";
import { hourlyIntervalOption } from "@/charts/options";
import { FilterBar, ModeToggle } from "@/components/site/filters";
import { SearchSelect } from "@/components/site/search-select";
import { ChartFrame, DataTable } from "@/components/story/chart-frame";
import { KpiRow } from "@/components/story/kpi-figure";
import { Definitions } from "@/components/story/page-parts";
import { HOUR_COLUMNS, stopIndex, stopRoute, type Meta, type StopIndex, type StopRoute } from "@/data/schemas";
import { useUrlState } from "@/hooks/use-url-state";
import { useView, type Initial } from "@/hooks/use-view";
import { count, pct, seconds } from "@/lib/format";

type Stop = StopRoute["stops"][number];
const col = Object.fromEntries(HOUR_COLUMNS.map((c, i) => [c, i])) as Record<(typeof HOUR_COLUMNS)[number], number>;

export const stopKey = (s: Pick<Stop, "direction_id" | "stop_id">) => `${s.direction_id ?? "-"}:${s.stop_id}`;

function StopDetail({ stop, figures, source, minCellNote }: { stop: Stop; figures: StopRoute["figures"]; source: Initial<StopRoute>["source"]; minCellNote: string }) {
  const hours = stop.hours.map((h) => ({
    label: String(h[col.service_hour]),
    value: h[col.on_time_share] as number | null,
    low: h[col.ci_low] as number | null,
    high: h[col.ci_high] as number | null,
    thin: !h[col.sufficient],
    events: h[col.events] as number,
    p50: h[col.p50_delay_s] as number | null,
    p90: h[col.p90_delay_s] as number | null,
  }));
  const build = useCallback((font: string) => hourlyIntervalOption(hours, font), [hours]);
  return (
    <>
      <div className="mt-6">
        <KpiRow
          size="md"
          figures={figures.map((f) => ({ ...f, value: stop.values[f.key] ?? null, display: stop.display[f.key] }))}
        />
      </div>
      <ChartFrame
        title={`Hour by hour at ${stop.stop_name ?? stop.stop_id}`}
        summary={`On-time share (dot) and 95 % Wilson interval (line) for each scheduled hour at this stop, both service days pooled. ${minCellNote}`}
        chart={<EChart build={build} height={300} label={`On-time share by hour at ${stop.label}`} />}
        table={
          <DataTable
            caption={`Hour by hour at ${stop.label}`}
            rows={hours}
            rowKey={(h) => h.label}
            columns={[
              { key: "hour", label: "Hour", render: (h) => h.label },
              { key: "events", label: "Arrivals", numeric: true, render: (h) => count(h.events) },
              { key: "on_time", label: "On time", numeric: true, render: (h) => pct(h.value, 0) },
              { key: "ci", label: "95 % interval", numeric: true, render: (h) => `${pct(h.low, 0)} – ${pct(h.high, 0)}` },
              { key: "p50", label: "Typical delay", numeric: true, render: (h) => seconds(h.p50) },
              { key: "p90", label: "Bad-day delay (p90)", numeric: true, render: (h) => seconds(h.p90) },
              { key: "data", label: "Data", render: (h) => (h.thin ? "too few to score" : "enough") },
            ]}
          />
        }
        source={source}
      />
    </>
  );
}

function Explorer({
  meta,
  initialIndex,
  initialRoute,
}: {
  meta: Meta;
  initialIndex: Initial<StopIndex>;
  initialRoute: Initial<StopRoute>;
}) {
  const modes = meta.modes.map((m) => m.key);
  const [state, setState] = useUrlState({ mode: modes[0], route: "", stop: "" }, { mode: modes });
  const index = useView<StopIndex>(`stops/${state.mode}/index.json`, stopIndex, initialIndex);
  const route = index.data.routes.find((r) => r.route_id === state.route) ?? index.data.routes[0];
  const routeView = useView<StopRoute>(`stops/${state.mode}/${route.file}`, stopRoute, initialRoute);
  const stops = routeView.data.stops;
  const stop = stops.find((s) => stopKey(s) === state.stop) ?? stops[0];
  const pending = index.pending || routeView.pending;
  return (
    <>
      <FilterBar>
        <ModeToggle modes={meta.modes} value={state.mode} onChange={(mode) => setState({ mode, route: "", stop: "" })} />
        <SearchSelect
          label="Route"
          testId="route-select"
          placeholder="Find a route"
          value={route.route_id}
          options={index.data.routes.map((r) => ({ value: r.route_id, label: `${r.route_id} · ${r.stops} stops` }))}
          onChange={(value) => setState({ route: value, stop: "" })}
        />
        {stop ? (
          <SearchSelect
            label="Stop"
            testId="stop-select"
            placeholder="Find a stop"
            value={stopKey(stop)}
            options={stops.map((s) => ({ value: stopKey(s), label: s.label }))}
            onChange={(value) => setState({ stop: value })}
          />
        ) : null}
        <span aria-live="polite" className="text-xs text-muted-ink">
          {pending ? "Loading…" : ""}
        </span>
      </FilterBar>
      <div className={pending ? "opacity-60" : ""} data-testid="view">
        {stop ? (
          <StopDetail
            stop={stop}
            figures={routeView.data.figures}
            source={routeView.source}
            minCellNote={`Hollow grey dots are hours with fewer than ${index.data.min_cell_events} arrivals: shown for completeness, not scored.`}
          />
        ) : (
          <p className="my-10">No stop of this route was observed often enough.</p>
        )}
      </div>
      <Definitions text={index.data.definitions} />
    </>
  );
}

export function StopsView(props: {
  meta: Meta;
  initialIndex: Initial<StopIndex>;
  initialRoute: Initial<StopRoute>;
}) {
  return <Explorer {...props} />;
}
