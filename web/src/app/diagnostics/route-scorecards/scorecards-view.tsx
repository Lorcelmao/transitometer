"use client";

import { useCallback } from "react";

import { EChart } from "@/charts/echart";
import { routeIntervalOption } from "@/charts/options";
import { ModeDayView } from "@/components/site/mode-day-view";
import { ChartFrame, DataTable } from "@/components/story/chart-frame";
import { Definitions } from "@/components/story/page-parts";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { scorecards, type Meta, type ScorecardRoute, type Scorecards } from "@/data/schemas";
import { useUrlState } from "@/hooks/use-url-state";
import type { Initial } from "@/hooks/use-view";
import { count, pct } from "@/lib/format";

const SHOWS = ["least", "most"] as const;

function Body({ data, source }: { data: Scorecards; source: Initial<Scorecards>["source"] }) {
  const [state, setState] = useUrlState({ show: "least" }, { show: SHOWS });
  const shown: ScorecardRoute[] = state.show === "most" ? data.most : data.least;
  const build = useCallback(
    (font: string) =>
      routeIntervalOption(
        shown.map((r) => ({ label: r.route_id, value: r.on_time_share, low: r.ci_low, high: r.ci_high })),
        font,
      ),
    [shown],
  );
  if (!data.ranked.length) {
    return (
      <p className="my-6 rounded-xl border border-rule bg-surface p-5 text-sm text-muted-ink">
        No route was observed often enough to be ranked.
      </p>
    );
  }
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2.5">
        <span id="show-label" className="text-[13px] font-medium text-muted-ink">
          Show
        </span>
        <ToggleGroup
          type="single"
          value={state.show}
          onValueChange={(v) => v && setState({ show: v })}
          aria-labelledby="show-label"
          className="inline-flex rounded-lg border border-rule bg-panel p-0.5"
          spacing={0}
        >
          <ToggleGroupItem
            value="least"
            className="min-h-10 rounded-md border-0 bg-transparent px-3.5 text-sm font-medium text-muted-ink shadow-none data-[state=on]:bg-surface data-[state=on]:font-semibold data-[state=on]:text-ink data-[state=on]:shadow-xs"
          >
            Least punctual
          </ToggleGroupItem>
          <ToggleGroupItem
            value="most"
            className="min-h-10 rounded-md border-0 bg-transparent px-3.5 text-sm font-medium text-muted-ink shadow-none data-[state=on]:bg-surface data-[state=on]:font-semibold data-[state=on]:text-ink data-[state=on]:shadow-xs"
          >
            Most punctual
          </ToggleGroupItem>
        </ToggleGroup>
      </div>
      <ChartFrame
        title={state.show === "most" ? "The most punctual routes" : "The least punctual routes"}
        summary={`On-time share (dot) and 95 % confidence interval (line) of the ${shown.length} ${state.show === "most" ? "most" : "least"} punctual ranked routes, both service days pooled. ${data.caption}`}
        chart={
          <EChart
            build={build}
            height={Math.max(280, 26 * shown.length + 76)}
            label="Route on-time share with 95 % intervals"
          />
        }
        table={
          <DataTable
            caption="Ranked routes"
            rows={data.ranked}
            rowKey={(r) => r.route_id}
            columns={[
              { key: "route", label: "Route", render: (r) => r.route_id },
              { key: "rank", label: "Rank", numeric: true, render: (r) => r.rank ?? "—" },
              { key: "on_time", label: "On time", numeric: true, render: (r) => pct(r.on_time_share) },
              {
                key: "ci",
                label: "95 % interval",
                numeric: true,
                render: (r) => `${pct(r.ci_low)} to ${pct(r.ci_high)}`,
              },
              { key: "ranks", label: "Plausible ranks", numeric: true, render: (r) => r.rank_interval },
              { key: "trips", label: "Trips", numeric: true, render: (r) => count(r.trips) },
              { key: "events", label: "Arrivals", numeric: true, render: (r) => count(r.events) },
            ]}
          />
        }
        note={
          data.unranked.length ? (
            <p>
              {data.unranked.length} route(s) had too few observations to be ranked:{" "}
              {data.unranked.map((r) => r.route_id).join(", ")}.
            </p>
          ) : null
        }
        source={source}
      />
      <Definitions text={data.definitions} />
    </div>
  );
}

export function ScorecardsView({ meta, initial }: { meta: Meta; initial: Initial<Scorecards> }) {
  return (
    <ModeDayView<Scorecards>
      meta={meta}
      page="scorecards"
      schema={scorecards}
      initial={initial}
      withDay={false}
      render={({ data, source }) => <Body data={data} source={source} />}
    />
  );
}
