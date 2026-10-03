"use client";

import { CircleCheck, CircleX } from "lucide-react";

import { DaySelect, FilterBar } from "@/components/site/filters";
import { ProvenanceLine } from "@/components/site/provenance-line";
import { DataTable } from "@/components/story/chart-frame";
import { Definitions } from "@/components/story/page-parts";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import type { FeedHealth, Meta, Source } from "@/data/schemas";
import { useUrlState } from "@/hooks/use-url-state";

export function FeedHealthView({ meta, data, source }: { meta: Meta; data: FeedHealth; source: Source }) {
  const days = Object.keys(data.views);
  const first = data.views[days[0]];
  const feedKeys = first.feeds.map((f) => f.feed);
  const [state, setState] = useUrlState({ day: days[0], feed: feedKeys[0] }, { day: days, feed: feedKeys });
  const view = data.views[state.day];
  const feed = view.feeds.find((f) => f.feed === state.feed) ?? view.feeds[0];
  return (
    <>
      <FilterBar>
        <DaySelect days={meta.days.filter((d) => days.includes(d.key))} value={state.day} onChange={(day) => setState({ day })} />
      </FilterBar>
      <dl className="grid gap-6 md:grid-cols-3">
        {view.feeds.map((f) => (
          <div key={f.feed} className="border-t-2 border-ink pt-2" data-testid={`feed-${f.feed}`}>
            <dt className="text-xs font-medium uppercase tracking-wider text-muted-ink">{f.label}</dt>
            <dd className="num mt-1 text-3xl md:text-4xl">{f.display}</dd>
            <dd className="mt-1 text-sm text-muted-ink">{f.help}</dd>
            <dd className="mt-2 flex items-start gap-1.5 text-sm">
              {f.failed.length ? (
                <>
                  <CircleX className="mt-0.5 size-4 shrink-0 text-fail" aria-hidden="true" />
                  <span>
                    <span className="font-semibold text-fail">Failed:</span> {f.failed.join(", ")}
                  </span>
                </>
              ) : (
                <>
                  <CircleCheck className="mt-0.5 size-4 shrink-0 text-pass" aria-hidden="true" />
                  <span className="font-semibold text-pass">All checks passed</span>
                </>
              )}
            </dd>
          </div>
        ))}
      </dl>
      <section aria-labelledby="checks" className="mt-12">
        <div className="flex flex-wrap items-baseline justify-between gap-3 border-b border-ink pb-2">
          <h2 id="checks" className="font-display text-2xl md:text-3xl">
            Every check, {view.day_label}
          </h2>
          <ToggleGroup
            type="single"
            value={feed.feed}
            onValueChange={(v) => v && setState({ feed: v })}
            aria-label="Feed"
            variant="outline"
            spacing={0}
            className="flex-wrap"
          >
            {view.feeds.map((f) => (
              <ToggleGroupItem key={f.feed} value={f.feed} className="min-h-11 rounded-none px-3 data-[state=on]:bg-ink data-[state=on]:text-paper">
                {f.label}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        </div>
        <div className="mt-4">
          <DataTable
            caption={`Quality checks of ${feed.label}, ${view.day_label}`}
            rows={feed.checks}
            rowKey={(c) => c.metric}
            columns={[
              { key: "check", label: "Check", render: (c) => c.check },
              {
                key: "result",
                label: "Result",
                render: (c) => (
                  <span className={`font-semibold ${c.passed ? "text-pass" : "text-fail"}`}>{c.result}</span>
                ),
              },
              { key: "measured", label: "Measured", numeric: true, render: (c) => c.measured },
              { key: "threshold", label: "Threshold", numeric: true, render: (c) => c.threshold_display },
              { key: "what", label: "What it measures", render: (c) => c.description },
            ]}
          />
        </div>
        <div className="mt-3">
          <ProvenanceLine source={source} />
        </div>
      </section>
      <Definitions text={view.definitions} />
    </>
  );
}
