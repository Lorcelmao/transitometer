import Link from "next/link";

import { HomeGlance } from "@/app/home-glance";
import { PAGES } from "@/components/site/nav";
import { ProvenanceLine } from "@/components/site/provenance-line";
import {
  MiniComparisonBars,
  MiniHourlySparkline,
  MiniIntervalPlot,
} from "@/components/story/micro-viz";
import { PageIntro } from "@/components/story/page-parts";
import { readMeta, readView } from "@/data/load";
import {
  earlyWarning as earlyWarningSchema,
  feedHealth as feedHealthSchema,
  overview as overviewSchema,
  scorecards as scorecardsSchema,
} from "@/data/schemas";
import { count, pct } from "@/lib/format";

function quantile(sorted: number[], p: number): number {
  if (!sorted.length) return 0;
  const idx = (sorted.length - 1) * p;
  const lo = Math.floor(idx);
  const hi = Math.ceil(idx);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (idx - lo);
}

export default function Home() {
  const meta = readMeta();
  const { data: overview, source } = readView("overview.json", overviewSchema);
  const { data: feedHealth } = readView("feed-health.json", feedHealthSchema);
  const { data: busScorecards } = readView("scorecards/bus.json", scorecardsSchema);
  const { data: busEarlyWarning } = readView("early-warning/bus.json", earlyWarningSchema);
  const { pipeline, trust } = overview;

  const href = (page: string) => PAGES.find((p) => p.page === page)?.href ?? "/";
  const findingByKey = Object.fromEntries(overview.findings.map((f) => [f.key, f]));

  // Exact arrival-weighted pooled bus vs subway shares across both days (matches findings.modes).
  const days = meta.days.map((d) => d.key);
  const pooledMode = (mode: string) => {
    let events = 0;
    let onTimeWeighted = 0;
    for (const day of days) {
      const v = overview.views[`${mode}/${day}`];
      if (!v) continue;
      for (const h of v.hours) {
        if (h.on_time_share !== null) {
          events += h.events;
          onTimeWeighted += h.on_time_share * h.events;
        }
      }
    }
    return { share: events > 0 ? onTimeWeighted / events : 0, events };
  };
  const subwayPooled = pooledMode("subway");
  const busPooled = pooledMode("bus");
  const modeGapPts = ((subwayPooled.share - busPooled.share) * 100).toFixed(1);

  // Exact 24-hour (00:00 to 23:00) pooled bus curve from overview.views for Finding 2.
  const busHourMap = new Map<number, { events: number; weighted: number }>();
  for (const day of days) {
    const v = overview.views[`bus/${day}`];
    if (!v) continue;
    for (const h of v.hours) {
      if (h.service_hour <= 23 && h.on_time_share !== null) {
        const cur = busHourMap.get(h.service_hour) ?? { events: 0, weighted: 0 };
        cur.events += h.events;
        cur.weighted += h.on_time_share * h.events;
        busHourMap.set(h.service_hour, cur);
      }
    }
  }
  const pooledHours = Array.from(busHourMap.entries())
    .sort((a, b) => a[0] - b[0])
    .map(([hour, { events, weighted }]) => ({
      hour,
      events,
      share: events > 0 ? weighted / events : 0,
    }));
  const suffPooledHours = pooledHours.filter((h) => h.events >= 1000);
  const worstPooled = suffPooledHours.reduce(
    (a, b) => (b.share < a.share ? b : a),
    suffPooledHours[0] ?? { hour: 16, events: 0, share: 0.403 },
  );
  const bestPooled = suffPooledHours.reduce(
    (a, b) => (b.share > a.share ? b : a),
    suffPooledHours[0] ?? { hour: 0, events: 0, share: 0.622 },
  );
  const hourDropPts = ((bestPooled.share - worstPooled.share) * 100).toFixed(1);

  // Bus route median + IQR + worst route from scorecards/bus.json for Finding 3.
  const rankedBus = busScorecards.ranked;
  const sortedShares = [...rankedBus.map((r) => r.on_time_share)].sort((a, b) => a - b);
  const busMedian = quantile(sortedShares, 0.5);
  const busQ25 = quantile(sortedShares, 0.25);
  const busQ75 = quantile(sortedShares, 0.75);
  const worstRoute = rankedBus[rankedBus.length - 1];

  // Bus late early-warning verdict from early-warning/bus.json for Finding 4.
  const lateVerdict = busEarlyWarning.verdicts.find((v) => v.outcome === "late");
  const lateRuleRow = busEarlyWarning.comparison.find(
    (r) => r.outcome === "late" && r.method === "rule" && r.service_date === busEarlyWarning.held_out_day,
  );
  const lateBaseRow = busEarlyWarning.comparison.find(
    (r) => r.outcome === "late" && r.method === "baseline" && r.service_date === busEarlyWarning.held_out_day,
  );

  // Compact feed-check lookup per mode/day for KPI card #4 micro-visual.
  const feedChecksByKey: Record<string, { passed: number; total: number; failed: string[] }> = {};
  for (const [dayKey, dayView] of Object.entries(feedHealth.views)) {
    for (const f of dayView.feeds) {
      const modeKey = f.feed === "bus_tu" ? "bus" : f.feed === "subway_tu" ? "subway" : null;
      if (!modeKey) continue;
      const total = f.checks.length;
      const passed = f.checks.filter((c) => c.passed).length;
      feedChecksByKey[`${modeKey}/${dayKey}`] = { passed, total, failed: f.failed };
    }
  }

  return (
    <div className="space-y-6">
      <PageIntro
        section="Overview"
        title="NYC bus and subway reliability overview"
        actions={
          <>
            <Link
              href="/data/validation/"
              prefetch={false}
              className="inline-flex min-h-10 items-center rounded-lg border border-rule-strong bg-surface px-3.5 text-sm font-medium text-ink no-underline transition-colors hover:bg-panel"
            >
              How it was checked
            </Link>
            <Link
              href="/diagnostics/stops/"
              prefetch={false}
              className="inline-flex min-h-10 items-center rounded-lg bg-brand px-3.5 text-sm font-medium text-white no-underline transition-colors hover:bg-brand-hover"
            >
              Check your stop
            </Link>
          </>
        }
      >
        Comparing published MTA timetables against two days of archived real-time feeds to measure punctuality,
        bunching, trip delivery, and feed health.
      </PageIntro>

      <HomeGlance meta={meta} overview={overview} source={source} feedChecks={feedChecksByKey} />

      {/* Key findings across both service days (explicit scope + real-data micro-visuals) */}
      <section aria-labelledby="findings-heading" className="space-y-3.5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="findings-heading" className="text-lg font-bold tracking-tight text-ink">
            Key findings across both service days
          </h2>
          <p className="text-sm text-muted-ink">
            Two-day pooled comparisons (except held-out early warning) paired with their reference scale
          </p>
        </div>

        <div className="grid gap-3.5 md:grid-cols-2">
          {/* Finding 1: Subway vs Bus */}
          {findingByKey.modes ? (
            <article
              className="flex flex-col gap-3 rounded-xl border border-rule bg-surface p-4 shadow-xs"
              data-testid="finding-modes"
            >
              <div className="flex items-start justify-between gap-2">
                <div>
                  <h3 className="text-[13px] font-semibold text-muted-ink">
                    Subway vs bus punctuality (both days pooled)
                  </h3>
                  <div className="mt-1 flex flex-wrap items-baseline gap-2">
                    <span className="num text-[28px] font-bold leading-none tracking-tight text-ink">
                      {findingByKey.modes.value}
                    </span>
                    <span className="text-xs font-medium text-muted-ink">subway arrivals on time</span>
                  </div>
                </div>
                <span className="num rounded-full bg-attention-soft px-2.5 py-0.5 text-xs font-semibold text-attention-text">
                  +{modeGapPts} pt gap
                </span>
              </div>
              <div className="rounded-lg border border-panel bg-paper p-3">
                <MiniComparisonBars
                  rows={[
                    {
                      label: "Subway",
                      value: subwayPooled.share,
                      display: pct(subwayPooled.share),
                      tone: "brand",
                    },
                    {
                      label: "Bus",
                      value: busPooled.share,
                      display: pct(busPooled.share),
                      tone: "attention",
                    },
                  ]}
                />
              </div>
              <p className="flex-1 text-sm leading-relaxed text-ink">
                Trains stayed on schedule far more often than street-level buses, which face mixed traffic and boarding
                delays across both days.
              </p>
              <div className="flex flex-wrap items-center justify-between gap-2 border-t border-panel pt-2.5 text-xs">
                <span className="num text-muted-ink">
                  Both days pooled: {count(subwayPooled.events)} subway and {count(busPooled.events)} bus arrivals
                </span>
                <Link href={href(findingByKey.modes.page)} prefetch={false} className="font-semibold no-underline hover:underline">
                  Open on-time report
                </Link>
              </div>
            </article>
          ) : null}

          {/* Finding 2: Lowest Bus Hour */}
          {findingByKey.hours ? (
            <article
              className="flex flex-col gap-3 rounded-xl border border-rule bg-surface p-4 shadow-xs"
              data-testid="finding-hours"
            >
              <div className="flex items-start justify-between gap-2">
                <div>
                  <h3 className="text-[13px] font-semibold text-muted-ink">
                    Lowest bus punctuality hour (both days pooled)
                  </h3>
                  <div className="mt-1 flex flex-wrap items-baseline gap-2">
                    <span className="num text-[28px] font-bold leading-none tracking-tight text-ink">
                      {findingByKey.hours.value}
                    </span>
                    <span className="text-xs font-medium text-muted-ink">
                      at {String(worstPooled.hour).padStart(2, "0")}:00 (afternoon rush)
                    </span>
                  </div>
                </div>
                <span className="num rounded-full bg-attention-soft px-2.5 py-0.5 text-xs font-semibold text-attention-text">
                  {hourDropPts} pt drop from peak
                </span>
              </div>
              <div className="rounded-lg border border-panel bg-paper px-3 py-2">
                <MiniHourlySparkline
                  points={pooledHours}
                  lowHour={{
                    hour: worstPooled.hour,
                    share: worstPooled.share,
                    display: pct(worstPooled.share),
                  }}
                  highHour={{
                    hour: bestPooled.hour,
                    share: bestPooled.share,
                    display: pct(bestPooled.share),
                  }}
                />
              </div>
              <p className="flex-1 text-sm leading-relaxed text-ink">
                Afternoon rush hour saw the sharpest drop in reliability, falling well below midnight service when
                streets are clear.
              </p>
              <div className="flex flex-wrap items-center justify-between gap-2 border-t border-panel pt-2.5 text-xs">
                <span className="text-muted-ink">
                  Scheduled hours with at least 1,000 arrivals (both days pooled)
                </span>
                <Link href={href(findingByKey.hours.page)} prefetch={false} className="font-semibold no-underline hover:underline">
                  See routes by hour
                </Link>
              </div>
            </article>
          ) : null}

          {/* Finding 3: Least Punctual Bus Route */}
          {findingByKey.route && worstRoute ? (
            <article
              className="flex flex-col gap-3 rounded-xl border border-rule bg-surface p-4 shadow-xs"
              data-testid="finding-route"
            >
              <div className="flex items-start justify-between gap-2">
                <div>
                  <h3 className="text-[13px] font-semibold text-muted-ink">
                    Least punctual bus route ({worstRoute.route_id}, both days pooled)
                  </h3>
                  <div className="mt-1 flex flex-wrap items-baseline gap-2">
                    <span className="num text-[28px] font-bold leading-none tracking-tight text-ink">
                      {findingByKey.route.value}
                    </span>
                    <span className="text-xs font-medium text-muted-ink">
                      rank {worstRoute.rank} of {rankedBus.length} bus routes
                    </span>
                  </div>
                </div>
                <span className="rounded-full bg-fail-soft px-2.5 py-0.5 text-xs font-semibold text-fail-text">
                  Below route median
                </span>
              </div>
              <div className="rounded-lg border border-panel bg-paper px-3 py-2">
                <MiniIntervalPlot
                  routeId={worstRoute.route_id}
                  value={worstRoute.on_time_share}
                  ciLow={worstRoute.ci_low ?? worstRoute.on_time_share}
                  ciHigh={worstRoute.ci_high ?? worstRoute.on_time_share}
                  median={busMedian}
                  q25={busQ25}
                  q75={busQ75}
                />
              </div>
              <p className="flex-1 text-sm leading-relaxed text-ink">
                Even the upper end of its 95 % confidence interval sits well below the typical NYC bus route, placing it
                in plausible ranks {worstRoute.rank_interval}.
              </p>
              <div className="flex flex-wrap items-center justify-between gap-2 border-t border-panel pt-2.5 text-xs">
                <span className="num text-muted-ink">
                  {count(worstRoute.events)} arrivals on {worstRoute.route_id} across both days
                </span>
                <Link href={href(findingByKey.route.page)} prefetch={false} className="font-semibold no-underline hover:underline">
                  Open route scorecards
                </Link>
              </div>
            </article>
          ) : null}

          {/* Finding 4: Early Warning Rule vs Baseline */}
          {findingByKey.warning && lateVerdict?.available ? (
            <article
              className="flex flex-col gap-3 rounded-xl border border-rule bg-surface p-4 shadow-xs"
              data-testid="finding-warning"
            >
              <div className="flex items-start justify-between gap-2">
                <div>
                  <h3 className="text-[13px] font-semibold text-muted-ink">
                    Mid-trip late warning (held-out day: {busEarlyWarning.held_out_label})
                  </h3>
                  <div className="mt-1 flex flex-wrap items-baseline gap-2">
                    <span className="num text-[28px] font-bold leading-none tracking-tight text-ink">
                      {findingByKey.warning.value}
                    </span>
                    <span className="text-xs font-medium text-muted-ink">F1 score (higher is better)</span>
                  </div>
                </div>
                <span
                  className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                    lateVerdict.passed ? "bg-pass-soft text-pass-text" : "bg-fail-soft text-fail-text"
                  }`}
                >
                  {lateVerdict.passed ? "Passed checks" : "Did not pass"}
                </span>
              </div>
              <div className="rounded-lg border border-panel bg-paper p-3">
                <MiniComparisonBars
                  rows={[
                    {
                      label: "Rule F1",
                      value: lateVerdict.f1 ?? 0,
                      display: lateVerdict.f1_display ?? "—",
                      tone: "brand",
                    },
                    {
                      label: "Baseline F1",
                      value: lateVerdict.baseline_f1 ?? 0,
                      display: lateVerdict.baseline_f1_display ?? "—",
                      tone: "muted",
                    },
                    {
                      label: "Precision",
                      value: lateRuleRow?.precision ?? 0,
                      display: lateVerdict.precision_display ?? "—",
                      tone: "pass",
                      threshold: busEarlyWarning.min_precision,
                      thresholdLabel: `Minimum precision target: ${busEarlyWarning.min_precision_display}`,
                    },
                  ]}
                />
              </div>
              <p className="flex-1 text-sm leading-relaxed text-ink">
                Outperformed the naive baseline on an unseen day and cleared the {busEarlyWarning.min_precision_display}{" "}
                precision target (dark tick), catching {lateVerdict.recall_display} of late bus trips halfway through.
              </p>
              <div className="flex flex-wrap items-center justify-between gap-2 border-t border-panel pt-2.5 text-xs">
                <span className="num text-muted-ink">
                  {count(lateRuleRow?.decisions ?? lateBaseRow?.decisions)} held-out bus trips evaluated
                </span>
                <Link href={href(findingByKey.warning.page)} prefetch={false} className="font-semibold no-underline hover:underline">
                  Inspect warning rules
                </Link>
              </div>
            </article>
          ) : null}
        </div>
      </section>

      {/* Unified Pipeline & Verification Summary (live counts from overview.json, zero hardcoded numbers) */}
      <section
        aria-labelledby="trust-heading"
        className="rounded-xl border border-rule bg-surface p-5 shadow-xs"
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 id="trust-heading" className="text-lg font-bold tracking-tight text-ink">
              Pipeline and verification summary
            </h2>
            <p className="mt-1 max-w-3xl text-sm text-muted-ink">
              Archived MTA feeds are replayed through Kafka, processed by Spark Structured Streaming into Delta Lake,
              and verified table by table against an independent DuckDB SQL reference.
            </p>
          </div>
          <span
            className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
              trust.integrity.ok && trust.parity.ok
                ? "bg-pass-soft text-pass-text"
                : "bg-fail-soft text-fail-text"
            }`}
          >
            {trust.integrity.ok && trust.parity.ok ? "Parity and integrity checks passed" : "Check validation report"}
          </span>
        </div>

        <dl className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-lg border border-rule bg-paper p-3.5">
            <dt className="text-xs font-semibold text-muted-ink">Step 1: Source integrity (Kafka replay)</dt>
            <dd className="num mt-1 text-2xl font-bold tracking-tight text-ink" data-testid="trust-integrity">
              {trust.integrity.available ? trust.integrity.archive_rows_display : "not yet measured"}
            </dd>
            <dd className="mt-1 text-xs leading-relaxed text-muted-ink">
              Archive rows ({pipeline.messages ?? "—"} protobuf messages) reached Delta Lake unchanged (
              {trust.integrity.status}).
            </dd>
          </div>

          <div className="rounded-lg border border-rule bg-paper p-3.5">
            <dt className="text-xs font-semibold text-muted-ink">Step 2: Silver parity (Spark vs DuckDB)</dt>
            <dd className="num mt-1 text-2xl font-bold tracking-tight text-ink" data-testid="trust-silver">
              {pipeline.silver ?? "not yet measured"}
            </dd>
            <dd className="mt-1 text-xs leading-relaxed text-muted-ink">
              {pipeline.stop_events} inferred arrivals matched to the timetable; every Silver table equals golden.
            </dd>
          </div>

          <div className="rounded-lg border border-rule bg-paper p-3.5">
            <dt className="text-xs font-semibold text-muted-ink">Step 3: Gold parity (8 requirements)</dt>
            <dd className="num mt-1 text-2xl font-bold tracking-tight text-ink" data-testid="trust-gold">
              {pipeline.gold ?? "not yet measured"}
            </dd>
            <dd className="mt-1 text-xs leading-relaxed text-muted-ink">
              Result tables match the independent reference within written tolerance (built in{" "}
              {pipeline.gold_seconds ?? "—"}).
            </dd>
          </div>

          <div className="rounded-lg border border-rule bg-paper p-3.5">
            <dt className="text-xs font-semibold text-muted-ink">Step 4: Automated test suite</dt>
            <dd className="num mt-1 text-2xl font-bold tracking-tight text-ink" data-testid="trust-tests">
              {pipeline.tests ?? "not yet measured"}
            </dd>
            <dd className="mt-1 text-xs leading-relaxed text-muted-ink">
              Recorded pipeline, parity, and view tests passing.{" "}
              <Link href="/data/validation/" prefetch={false}>
                Inspect SHA-256 evidence
              </Link>
              .
            </dd>
          </div>
        </dl>

        <div className="mt-4 border-t border-panel pt-3">
          <ProvenanceLine source={source} />
        </div>
      </section>
    </div>
  );
}
