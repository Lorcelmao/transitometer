"use client";

import Link from "next/link";

import { Markdown } from "@/components/markdown";
import { DaySelect, FilterBar, ModeToggle } from "@/components/site/filters";
import { ChartFrame, DataTable } from "@/components/story/chart-frame";
import { HeroNetwork } from "@/components/story/hero";
import { HourlyProfile } from "@/components/story/hourly-profile";
import { KpiRow, type KpiExtra } from "@/components/story/kpi-figure";
import { CheckStrip, PeerCompareBar } from "@/components/story/micro-viz";
import { Caveat } from "@/components/story/page-parts";
import type { Meta, Overview, Source } from "@/data/schemas";
import { useUrlState } from "@/hooks/use-url-state";
import { count } from "@/lib/format";

function shortDay(label: string): string {
  return label.replace(/ \d{4}$/, "");
}

/**
 * Interactive Overview section: sticky mode/day filter bar, shared day takeaway from views.py,
 * 4 context-rich KPI cards (badges pre-computed in Python), and side-by-side Hourly Profile
 * + NYC Stop Map preview.
 */
export function HomeGlance({
  meta,
  overview,
  source,
}: {
  meta: Meta;
  overview: Overview;
  source: Source;
}) {
  const modes = meta.modes.map((m) => m.key);
  const days = meta.days.map((d) => d.key);
  const [state, setState] = useUrlState({ mode: modes[0], day: days[0] }, { mode: modes, day: days });
  const view = overview.views[`${state.mode}/${state.day}`];
  const peerMode = state.mode === "bus" ? "subway" : "bus";
  const peerView = overview.views[`${peerMode}/${state.day}`];
  const peerLabelShort = meta.modes.find((m) => m.key === peerMode)?.short ?? peerMode;
  const peerByKey = Object.fromEntries((peerView?.figures ?? []).map((f) => [f.key, f]));
  const byKey = Object.fromEntries(view.figures.map((f) => [f.key, f]));
  const dayShort = shortDay(view.day_label);
  const fc = view.feed_checks;
  const failCount = fc ? fc.total - fc.passed : 0;

  const modeName = state.mode === "bus" ? "MTA Bus" : "NYC Subway";
  const basisPlain = (basis: string | null | undefined) => (basis ? basis.replace(/^of /, "") : "");

  const extras: Record<string, KpiExtra> = {
    on_time: {
      viz:
        byKey.on_time?.value !== null && peerByKey.on_time?.value !== null ? (
          <PeerCompareBar
            value={byKey.on_time.value as number}
            peerValue={peerByKey.on_time.value as number}
            peerLabel={`${peerLabelShort} (${dayShort})`}
            peerDisplay={peerByKey.on_time.display}
            fillTone="brand"
            leftLabel="0 %"
            rightLabel="100 %"
          />
        ) : undefined,
      shortNote: `Within 1 min early to 5 min late (MTA standard), across ${basisPlain(byKey.on_time?.basis)}.`,
    },
    bunched: {
      viz:
        byKey.bunched?.value !== null && peerByKey.bunched?.value !== null ? (
          <PeerCompareBar
            value={byKey.bunched.value as number}
            peerValue={peerByKey.bunched.value as number}
            peerLabel={`${peerLabelShort} (${dayShort})`}
            peerDisplay={peerByKey.bunched.display}
            fillTone="attention"
            leftLabel="Lower is better"
          />
        ) : undefined,
      shortNote: `Vehicles arriving within 25 % of scheduled gap, out of ${basisPlain(byKey.bunched?.basis)}.`,
    },
    not_delivered: {
      viz:
        byKey.not_delivered?.value !== null && peerByKey.not_delivered?.value !== null ? (
          <PeerCompareBar
            value={byKey.not_delivered.value as number}
            peerValue={peerByKey.not_delivered.value as number}
            peerLabel={`${peerLabelShort} (${dayShort})`}
            peerDisplay={peerByKey.not_delivered.display}
            fillTone={byKey.not_delivered?.badge?.tone === "fail" ? "fail" : "attention"}
            leftLabel="Lower is better"
          />
        ) : undefined,
      shortNote: `Never reported or never moved in feed, from ${basisPlain(byKey.not_delivered?.basis)}.`,
    },
    feed_score: {
      viz: fc ? <CheckStrip passed={fc.passed} total={fc.total} /> : undefined,
      shortNote:
        fc && failCount > 0
          ? `Failed check${failCount > 1 ? "s" : ""}: ${fc.failed.join(", ")}.`
          : "All automated feed quality checks passed on this day.",
    },
  };

  return (
    <section aria-label="Service day summary" className="space-y-4">
      <FilterBar>
        <ModeToggle modes={meta.modes} value={state.mode} onChange={(mode) => setState({ mode })} />
        <DaySelect days={meta.days} value={state.day} onChange={(day) => setState({ day })} />
      </FilterBar>

      {/* Plain-English takeaway shared with Streamlit via views.overview */}
      <p
        key={`${state.mode}-${state.day}`}
        className="value-update rounded-lg border border-blue-200 border-l-4 border-l-brand bg-brand-soft px-4 py-3 text-[15px] leading-relaxed text-ink"
        data-testid="headline"
      >
        <strong className="font-semibold">
          Day takeaway ({view.day_label}, {modeName}):
        </strong>{" "}
        {view.takeaway}
      </p>

      {view.caveat ? (
        <Caveat>
          <Markdown className="inline [&>p]:inline">{view.caveat.text}</Markdown>
        </Caveat>
      ) : null}

      <KpiRow figures={view.figures} extras={extras} />

      {/* Side-by-side primary charts: Hourly profile (left) + NYC Stop Map preview (right) */}
      <div className="grid items-stretch gap-4 lg:grid-cols-12">
        <div className="lg:col-span-7">
          <ChartFrame
            className="my-0 flex h-full flex-col justify-between"
            title={`On-time share by hour (${modeName})`}
            lead={
              <p>
                All routes combined on {view.day_label}. Hours marked (+1) continue the same service day after
                midnight; hollow circles mark hours with fewer than {count(view.hourly_min_events)} arrivals.
              </p>
            }
            summary={`On-time share by scheduled hour on ${view.day_label} for ${view.group_label}. Hollow circles mark hours with fewer than ${count(view.hourly_min_events)} arrivals. Hours past midnight belong to the same service day (+1).`}
            chart={
              <HourlyProfile
                hours={view.hours}
                label={`On-time share by hour, ${view.group_label}, ${view.day_label}`}
              />
            }
            table={
              <DataTable
                caption="On-time share by hour"
                rows={view.hours}
                rowKey={(h) => String(h.service_hour)}
                columns={[
                  { key: "hour", label: "Hour", render: (h) => h.hour_label },
                  { key: "events", label: "Arrivals", numeric: true, render: (h) => count(h.events) },
                  {
                    key: "share",
                    label: "On time",
                    numeric: true,
                    render: (h) => (h.sufficient ? h.display : `${h.display} (few arrivals)`),
                  },
                ]}
              />
            }
            source={source}
          />
        </div>

        <section
          aria-labelledby="overview-map-title"
          className="flex flex-col overflow-hidden rounded-xl border border-rule bg-surface shadow-xs lg:col-span-5"
        >
          <div className="flex items-start justify-between gap-3 border-b border-panel px-4 py-3.5 md:px-5">
            <div className="min-w-0 flex-1">
              <h2 id="overview-map-title" className="text-[17px] font-semibold leading-snug text-ink">
                Stop reliability across NYC
              </h2>
              <p className="mt-1 text-sm text-muted-ink">
                {count(overview.hero.stops)} bus and subway stops, both service days pooled
              </p>
            </div>
            <Link
              href="/diagnostics/map/"
              prefetch={false}
              className="inline-flex min-h-10 shrink-0 items-center rounded-md border border-rule bg-paper px-3 text-xs font-semibold text-brand no-underline transition-colors hover:bg-brand-soft"
            >
              Open map
            </Link>
          </div>
          <div className="flex flex-1 flex-col justify-center px-4 py-3 md:px-5">
            <HeroNetwork hero={overview.hero} maxHeight={252} />
          </div>
          <footer className="flex flex-wrap items-center justify-between gap-2 border-t border-rule bg-paper px-4 py-3 text-xs text-muted-ink md:px-5">
            <span>Grey cells have fewer than 10 arrivals (not scored).</span>
            <Link href="/diagnostics/stops/" prefetch={false} className="font-semibold no-underline hover:underline">
              Stop explorer
            </Link>
          </footer>
        </section>
      </div>
    </section>
  );
}
