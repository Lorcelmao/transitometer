"use client";

import { Markdown } from "@/components/markdown";
import { DaySelect, FilterBar, ModeToggle } from "@/components/site/filters";
import { ChartFrame, DataTable } from "@/components/story/chart-frame";
import { HourlyProfile } from "@/components/story/hourly-profile";
import { KpiRow } from "@/components/story/kpi-figure";
import { Caveat } from "@/components/story/page-parts";
import type { Meta, Overview, Source } from "@/data/schemas";
import { useUrlState } from "@/hooks/use-url-state";
import { count } from "@/lib/format";

/** The day at a glance: four headline figures for one mode and day, their sentence, and the day hour by hour. */
export function HomeGlance({ meta, overview, source }: { meta: Meta; overview: Overview; source: Source }) {
  const modes = meta.modes.map((m) => m.key);
  const days = meta.days.map((d) => d.key);
  const [state, setState] = useUrlState({ mode: modes[0], day: days[0] }, { mode: modes, day: days });
  const view = overview.views[`${state.mode}/${state.day}`];
  const display = Object.fromEntries(view.figures.map((f) => [f.key, f.display]));
  const modeLabel = meta.modes.find((m) => m.key === state.mode)?.short.toLowerCase() ?? state.mode;
  return (
    <section aria-labelledby="glance" className="mt-20 scroll-mt-28" id="glance">
      <p className="text-xs font-medium uppercase tracking-widest text-accent-red">Chapter 1</p>
      <h2 id="glance" className="mt-1 font-display text-3xl md:text-4xl">
        The day at a glance
      </h2>
      <FilterBar>
        <ModeToggle modes={meta.modes} value={state.mode} onChange={(mode) => setState({ mode })} />
        <DaySelect days={meta.days} value={state.day} onChange={(day) => setState({ day })} />
      </FilterBar>
      <p key={`${state.mode}-${state.day}`} className="value-update max-w-3xl font-display text-2xl leading-snug md:text-3xl" data-testid="headline">
        On {view.day_label}, <span className="num">{display.on_time}</span> of {view.group_label} inferred arrivals were on
        time, <span className="num">{display.bunched}</span> of headways were bunched, and{" "}
        <span className="num">{display.not_delivered}</span> of the scheduled trips the feed could observe were never seen
        running.
      </p>
      <div className="mt-8">
        <KpiRow figures={view.figures} />
      </div>
      {view.caveat ? (
        <Caveat>
          <Markdown className="inline [&>p]:inline">{view.caveat.text}</Markdown>
        </Caveat>
      ) : null}
      <ChartFrame
        title={`When does ${modeLabel} punctuality slip?`}
        lead={<p>Share of inferred arrivals on time in each hour of the service day, all routes together.</p>}
        summary={`On-time share by scheduled hour on ${view.day_label} for ${view.group_label}. Hollow points are hours with fewer than ${count(view.hourly_min_events)} arrivals: shown, not compared. Hours past 23 belong to the same service day after midnight.`}
        chart={<HourlyProfile hours={view.hours} label={`On-time share by hour, ${view.group_label}, ${view.day_label}`} />}
        table={
          <DataTable
            caption="On-time share by hour"
            rows={view.hours}
            rowKey={(h) => String(h.service_hour)}
            columns={[
              { key: "hour", label: "Hour", render: (h) => `${String(h.service_hour).padStart(2, "0")}:00` },
              { key: "events", label: "Arrivals", numeric: true, render: (h) => count(h.events) },
              { key: "share", label: "On time", numeric: true, render: (h) => (h.sufficient ? h.display : `${h.display} (few arrivals)`) },
            ]}
          />
        }
        source={source}
      />
    </section>
  );
}
