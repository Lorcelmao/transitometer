"use client";

import { DaySelect, FilterBar } from "@/components/site/filters";
import { ProvenanceLine } from "@/components/site/provenance-line";
import { DataTable } from "@/components/story/chart-frame";
import { CheckStrip, ThresholdBullet } from "@/components/story/micro-viz";
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
    <div className="space-y-5">
      <FilterBar>
        <DaySelect
          days={meta.days.filter((d) => days.includes(d.key))}
          value={state.day}
          onChange={(day) => setState({ day })}
        />
      </FilterBar>

      {/* 3 Feed cards with discrete pass/fail check blocks */}
      <dl className="grid gap-3.5 md:grid-cols-3">
        {view.feeds.map((f) => {
          const selected = f.feed === feed.feed;
          return (
            <div
              key={f.feed}
              className={`flex flex-col gap-2.5 rounded-xl border bg-surface p-4 shadow-xs transition-colors ${
                selected ? "border-brand ring-1 ring-brand/25" : "border-rule"
              }`}
              data-testid={`feed-${f.feed}`}
            >
              <dt className="flex items-start justify-between gap-2 text-[13px] font-semibold text-muted-ink">
                <span>{f.label}</span>
                <span
                  className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                    f.badge.tone === "fail" ? "bg-fail-soft text-fail-text" : "bg-pass-soft text-pass-text"
                  }`}
                >
                  {f.badge.label}
                </span>
              </dt>
              <dd className="num text-[28px] font-bold leading-none tracking-tight text-ink">{f.display}</dd>
              <dd>
                <CheckStrip passed={f.passed} total={f.total} />
              </dd>
              <dd className="text-xs leading-relaxed text-muted-ink">
                {f.failed_count > 0
                  ? `${f.help}. Exceeded limit on: ${f.failed.join(", ")}.`
                  : `${f.help}. Every automated threshold met for this feed.`}
              </dd>
            </div>
          );
        })}
      </dl>

      {/* Check-by-check dashboard card with measured vs limit bullet bars */}
      <section
        aria-labelledby="checks"
        className="overflow-hidden rounded-xl border border-rule bg-surface shadow-xs"
      >
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-panel px-4 py-3.5 md:px-5">
          <div>
            <h2 id="checks" className="text-[17px] font-semibold text-ink">
              {feed.label}: check by check ({feed.passed} of {feed.total} passed, {view.day_label})
            </h2>
            <p className="mt-0.5 text-xs text-muted-ink">
              Lower values are better. Dark vertical tick marks the maximum allowed limit for each check.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <ToggleGroup
              type="single"
              value={feed.feed}
              onValueChange={(v) => v && setState({ feed: v })}
              aria-label="Feed"
              className="inline-flex flex-wrap rounded-lg border border-rule bg-panel p-0.5"
              spacing={0}
            >
              {view.feeds.map((f) => (
                <ToggleGroupItem
                  key={f.feed}
                  value={f.feed}
                  className="min-h-10 rounded-md border-0 bg-transparent px-3 text-xs font-medium text-muted-ink shadow-none data-[state=on]:bg-surface data-[state=on]:font-semibold data-[state=on]:text-ink data-[state=on]:shadow-xs"
                >
                  {f.label}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
            <span
              className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
                feed.status_badge.tone === "fail" ? "bg-fail-soft text-fail-text" : "bg-pass-soft text-pass-text"
              }`}
            >
              {feed.status_badge.label}
            </span>
          </div>
        </div>

        <div className="p-4 md:p-5">
          <DataTable
            caption={`Quality checks of ${feed.label}, ${view.day_label}`}
            rows={feed.checks}
            rowKey={(c) => c.metric}
            columns={[
              {
                key: "check",
                label: "Check",
                render: (c) => (
                  <div>
                    <p className="font-semibold text-ink">{c.check}</p>
                    <p className="text-xs font-normal text-muted-ink">{c.description}</p>
                  </div>
                ),
              },
              {
                key: "result",
                label: "Status",
                render: (c) => (
                  <span
                    className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                      c.passed ? "bg-pass-soft text-pass-text" : "bg-fail-soft text-fail-text"
                    }`}
                  >
                    {c.result}
                  </span>
                ),
              },
              {
                key: "bar",
                label: "Measured vs limit (dark tick = limit)",
                render: (c) => (
                  <ThresholdBullet
                    value={c.value}
                    threshold={c.threshold}
                    passed={c.passed}
                    measured={c.measured}
                    thresholdDisplay={c.threshold_display}
                  />
                ),
              },
              {
                key: "measured",
                label: "Measured",
                numeric: true,
                render: (c) => (
                  <span className={c.passed ? "font-medium text-ink" : "font-bold text-fail-text"}>
                    {c.measured}
                  </span>
                ),
              },
              { key: "threshold", label: "Limit", numeric: true, render: (c) => c.threshold_display },
            ]}
          />
        </div>

        <footer className="border-t border-rule bg-paper px-4 py-3 md:px-5">
          <ProvenanceLine source={source} />
        </footer>
      </section>

      <Definitions text={view.definitions} />
    </div>
  );
}
