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
  overview as overviewSchema,
  scorecards as scorecardsSchema,
  type Badge,
} from "@/data/schemas";
import { count } from "@/lib/format";

const BADGE_CLS: Record<Badge["tone"], string> = {
  pass: "bg-pass-soft text-pass-text",
  fail: "bg-fail-soft text-fail-text",
  attention: "bg-attention-soft text-attention-text",
  neutral: "bg-panel text-muted-ink",
};

type ModesStats = {
  subway_share: number;
  subway_display: string;
  subway_events: number;
  bus_share: number;
  bus_display: string;
  bus_events: number;
};
type HoursStats = {
  worst_hour: number;
  worst_hour_label: string;
  worst_share: number;
  worst_display: string;
  best_hour: number;
  best_hour_label: string;
  best_share: number;
  best_display: string;
  points: { hour: number; share: number }[];
};
type RouteStats = { median: number; q25: number; q75: number };

export default function Home() {
  const meta = readMeta();
  const { data: overview, source } = readView("overview.json", overviewSchema);
  const { data: busScorecards } = readView("scorecards/bus.json", scorecardsSchema);
  const { data: busEarlyWarning } = readView("early-warning/bus.json", earlyWarningSchema);
  const { pipeline, trust } = overview;

  const href = (page: string) => PAGES.find((p) => p.page === page)?.href ?? "/";
  const findingByKey = Object.fromEntries(overview.findings.map((f) => [f.key, f]));

  const modesStats = findingByKey.modes?.stats as ModesStats | undefined;
  const hoursStats = findingByKey.hours?.stats as HoursStats | undefined;
  const routeStats = findingByKey.route?.stats as RouteStats | undefined;

  const rankedBus = busScorecards.ranked;
  const worstRoute = rankedBus[rankedBus.length - 1];

  const lateVerdict = busEarlyWarning.verdicts.find((v) => v.outcome === "late");
  const lateRuleRow = busEarlyWarning.comparison.find(
    (r) => r.outcome === "late" && r.method === "rule" && r.service_date === busEarlyWarning.held_out_day,
  );
  const lateBaseRow = busEarlyWarning.comparison.find(
    (r) => r.outcome === "late" && r.method === "baseline" && r.service_date === busEarlyWarning.held_out_day,
  );

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

      <HomeGlance meta={meta} overview={overview} source={source} />

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
          {findingByKey.modes && modesStats ? (
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
                <span className={`num rounded-full px-2.5 py-0.5 text-xs font-semibold ${BADGE_CLS[findingByKey.modes.badge.tone]}`}>
                  {findingByKey.modes.badge.label}
                </span>
              </div>
              <div className="rounded-lg border border-panel bg-paper p-3">
                <MiniComparisonBars
                  rows={[
                    {
                      label: "Subway",
                      value: modesStats.subway_share,
                      display: modesStats.subway_display,
                      tone: "brand",
                    },
                    {
                      label: "Bus",
                      value: modesStats.bus_share,
                      display: modesStats.bus_display,
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
                  Both days pooled: {count(modesStats.subway_events)} subway and {count(modesStats.bus_events)} bus
                  arrivals
                </span>
                <Link href={href(findingByKey.modes.page)} prefetch={false} className="font-semibold no-underline hover:underline">
                  Open on-time report
                </Link>
              </div>
            </article>
          ) : null}

          {/* Finding 2: Lowest Bus Hour */}
          {findingByKey.hours && hoursStats ? (
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
                      at {hoursStats.worst_hour_label} (afternoon rush)
                    </span>
                  </div>
                </div>
                <span className={`num rounded-full px-2.5 py-0.5 text-xs font-semibold ${BADGE_CLS[findingByKey.hours.badge.tone]}`}>
                  {findingByKey.hours.badge.label}
                </span>
              </div>
              <div className="rounded-lg border border-panel bg-paper px-3 py-2">
                <MiniHourlySparkline
                  points={hoursStats.points}
                  lowHour={{
                    hour: hoursStats.worst_hour,
                    share: hoursStats.worst_share,
                    display: hoursStats.worst_display,
                  }}
                  highHour={{
                    hour: hoursStats.best_hour,
                    share: hoursStats.best_share,
                    display: hoursStats.best_display,
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
          {findingByKey.route && worstRoute && routeStats ? (
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
                <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${BADGE_CLS[findingByKey.route.badge.tone]}`}>
                  {findingByKey.route.badge.label}
                </span>
              </div>
              <div className="rounded-lg border border-panel bg-paper px-3 py-2">
                <MiniIntervalPlot
                  routeId={worstRoute.route_id}
                  value={worstRoute.on_time_share}
                  ciLow={worstRoute.ci_low ?? worstRoute.on_time_share}
                  ciHigh={worstRoute.ci_high ?? worstRoute.on_time_share}
                  median={routeStats.median}
                  q25={routeStats.q25}
                  q75={routeStats.q75}
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
                <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${BADGE_CLS[findingByKey.warning.badge.tone]}`}>
                  {findingByKey.warning.badge.label}
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
          <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${BADGE_CLS[trust.badge.tone]}`}>
            {trust.badge.label}
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
