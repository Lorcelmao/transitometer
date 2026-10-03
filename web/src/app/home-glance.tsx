"use client";

import { DaySelect, FilterBar, ModeToggle } from "@/components/site/filters";
import { KpiRow } from "@/components/story/kpi-figure";
import type { Meta, Overview } from "@/data/schemas";
import { useUrlState } from "@/hooks/use-url-state";

/** The day at a glance: four headline figures for one mode and day, and the sentence they make. */
export function HomeGlance({ meta, overview }: { meta: Meta; overview: Overview }) {
  const modes = meta.modes.map((m) => m.key);
  const days = meta.days.map((d) => d.key);
  const [state, setState] = useUrlState({ mode: modes[0], day: days[0] }, { mode: modes, day: days });
  const view = overview.views[`${state.mode}/${state.day}`];
  const display = Object.fromEntries(view.figures.map((f) => [f.key, f.display]));
  return (
    <section aria-labelledby="glance" className="mt-14">
      <h2 id="glance" className="text-xs font-medium uppercase tracking-widest text-muted-ink">
        The day at a glance
      </h2>
      <FilterBar>
        <ModeToggle modes={meta.modes} value={state.mode} onChange={(mode) => setState({ mode })} />
        <DaySelect days={meta.days} value={state.day} onChange={(day) => setState({ day })} />
      </FilterBar>
      <p className="max-w-3xl font-display text-2xl leading-snug md:text-3xl" data-testid="headline">
        On {view.day_label}, <span className="num">{display.on_time}</span> of {view.group_label} arrivals were
        on time, <span className="num">{display.bunched}</span> of headways were bunched, and{" "}
        <span className="num">{display.not_delivered}</span> of the scheduled trips the feed could observe were
        not delivered.
      </p>
      <div className="mt-8">
        <KpiRow figures={view.figures} />
      </div>
    </section>
  );
}
