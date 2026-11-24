"use client";

import { CircleCheck, CircleX } from "lucide-react";

import { ModeDayView } from "@/components/site/mode-day-view";
import { BarList, PairedBars } from "@/components/story/bar-list";
import { ChartFrame, DataTable } from "@/components/story/chart-frame";
import { Definitions } from "@/components/story/page-parts";
import { earlyWarning, type EarlyWarning, type Meta } from "@/data/schemas";
import type { Initial } from "@/hooks/use-view";
import { count, decimal, pct } from "@/lib/format";

type Source = Initial<EarlyWarning>["source"];

/**
 * What the rules would have shown a dispatcher on the held-out day: where and when they warned,
 * how many warnings came true, and example trips. Every number and string comes from the view.
 */
function Dispatcher({ data, source }: { data: EarlyWarning["dispatcher"]; source: Source }) {
  if (!data.available) return null;
  const routes = data.routes ?? [];
  const hours = data.hours ?? [];
  const examples = data.examples ?? [];
  return (
    <section aria-labelledby="dispatcher" className="mt-14">
      <h2 id="dispatcher" className="border-b border-ink pb-2 font-display text-2xl md:text-3xl">
        What a dispatcher would have seen on {data.day_label}
      </h2>
      <p className="mt-3 max-w-prose">
        A replay of the held-out day: at each trip&apos;s decision point the rules either warned or stayed quiet, and
        the trip&apos;s real outcome shows whether the warning came true.
      </p>
      <ChartFrame
        title="Routes with the most warnings"
        summary={data.routes_caption ?? ""}
        chart={
          <BarList
            label="Warnings per route on the held-out day"
            rows={routes.map((r) => ({
              key: r.route_id,
              label: r.route_id,
              share: r.bar,
              display: `${count(r.warnings)} warnings`,
              detail: `late warnings: ${r.late_display}`,
            }))}
          />
        }
        table={
          <DataTable
            caption="Warnings per route on the held-out day"
            rows={routes}
            rowKey={(r) => r.route_id}
            columns={[
              { key: "route", label: "Route", render: (r) => r.route_id },
              { key: "decisions", label: "Trips judged", numeric: true, render: (r) => count(r.decisions) },
              { key: "warnings", label: "Warnings", numeric: true, render: (r) => count(r.warnings) },
              { key: "late", label: "Late warnings", render: (r) => r.late_display },
              { key: "bunched", label: "Bunching warnings", render: (r) => r.bunched_display },
            ]}
          />
        }
        source={source}
      />
      <ChartFrame
        title="Warnings through the day"
        summary={data.hours_caption ?? ""}
        chart={
          <BarList
            label="Warnings per hour of the service day on the held-out day"
            rows={hours.map((h) => ({
              key: String(h.service_hour),
              label: h.label,
              share: h.bar,
              display: count(h.warnings),
              detail: `late warnings: ${h.late_display}`,
            }))}
          />
        }
        table={
          <DataTable
            caption="Warnings per hour on the held-out day"
            rows={hours}
            rowKey={(h) => String(h.service_hour)}
            columns={[
              { key: "hour", label: "Hour", render: (h) => h.label },
              { key: "decisions", label: "Trips judged", numeric: true, render: (h) => count(h.decisions) },
              { key: "warnings", label: "Warnings", numeric: true, render: (h) => count(h.warnings) },
              { key: "late", label: "Late warnings", render: (h) => h.late_display },
              { key: "bunched", label: "Bunching warnings", render: (h) => h.bunched_display },
            ]}
          />
        }
        source={source}
      />
      <section aria-labelledby="examples" className="my-10">
        <h3 id="examples" className="border-b border-ink pb-2 font-display text-xl md:text-2xl">
          Example warnings
        </h3>
        <p className="mt-3 max-w-prose text-sm text-muted-ink">{data.examples_caption}</p>
        <div className="mt-4">
          <DataTable
            caption="Example trips the late rule warned about"
            rows={examples}
            rowKey={(e) => `${e.kind}-${e.route_id}-${e.static_trip_id}`}
            columns={[
              { key: "route", label: "Route", render: (e) => e.route_id },
              { key: "kind", label: "Warning", render: (e) => e.kind },
              { key: "stop", label: "Decision stop", render: (e) => e.stop },
              { key: "time", label: "Time", numeric: true, render: (e) => e.time },
              { key: "delay", label: "Delay then", numeric: true, render: (e) => e.delay_display },
              { key: "projected", label: "Projected", numeric: true, render: (e) => e.projected_display },
              { key: "outcome", label: "Outcome", render: (e) => e.outcome },
            ]}
          />
        </div>
      </section>
    </section>
  );
}

function Body({ data, source }: { data: EarlyWarning; source: Source }) {
  const outcomes = Array.from(new Set(data.comparison.map((r) => r.outcome)));
  return (
    <>
      <section aria-labelledby="verdicts" className="mt-4">
        <h2 id="verdicts" className="border-b border-ink pb-2 font-display text-2xl md:text-3xl">
          Held-out day ({data.held_out_label}): did the rules pass?
        </h2>
        <div className="mt-6 grid gap-6 md:grid-cols-2">
          {data.verdicts.map((v) =>
            v.available ? (
              <article key={v.outcome} className="border-t-2 border-ink pt-3" data-testid={`verdict-${v.outcome}`}>
                <h3 className="flex items-center gap-2 text-lg font-semibold">
                  {v.passed ? (
                    <CircleCheck className="size-5 text-pass" aria-hidden="true" />
                  ) : (
                    <CircleX className="size-5 text-fail" aria-hidden="true" />
                  )}
                  {v.title}: <span className={v.passed ? "text-pass" : "text-fail"}>{v.verdict}</span>
                </h3>
                <p className="mt-2">
                  F1 <span className="num font-semibold">{v.f1_display}</span> vs baseline{" "}
                  <span className="num">{v.baseline_f1_display}</span> · precision{" "}
                  <span className="num font-semibold">{v.precision_display}</span> (target ≥{" "}
                  <span className="num">{data.min_precision_display}</span>) · recall{" "}
                  <span className="num">{v.recall_display}</span>
                </p>
                <p className="mt-1 text-sm text-muted-ink">{v.caption}</p>
              </article>
            ) : (
              <p key={v.outcome}>{v.title}: not measured.</p>
            ),
          )}
        </div>
      </section>
      <ChartFrame
        title="Rule vs baseline, both days"
        summary="F1 score of each warning rule and of its naive baseline, on the tuning day and on the held-out day (higher is better)."
        chart={
          <div className="grid gap-8 md:grid-cols-2">
            {outcomes.map((outcome) => (
              <div key={outcome}>
                <h3 className="mb-2 font-semibold capitalize">{outcome}</h3>
                <PairedBars
                  label={`F1 of the rule and the baseline, outcome ${outcome}`}
                  legend={["Baseline", "Rule"]}
                  scaleMax={1}
                  rows={Array.from(new Set(data.comparison.filter((r) => r.outcome === outcome).map((r) => r.day))).map((day) => {
                    const rows = data.comparison.filter((r) => r.outcome === outcome && r.day === day);
                    const rule = rows.find((r) => r.method === "rule");
                    const base = rows.find((r) => r.method === "baseline");
                    return {
                      key: `${outcome}-${day}`,
                      label: day,
                      a: base?.f1 ?? 0,
                      aDisplay: decimal(base?.f1, 3),
                      b: rule?.f1 ?? 0,
                      bDisplay: decimal(rule?.f1, 3),
                    };
                  })}
                />
              </div>
            ))}
          </div>
        }
        table={
          <DataTable
            caption="Rule and baseline, both days"
            rows={data.comparison}
            rowKey={(r) => `${r.outcome}-${r.service_date}-${r.method}`}
            columns={[
              { key: "outcome", label: "Outcome", render: (r) => r.outcome },
              { key: "day", label: "Day", render: (r) => r.day },
              { key: "method", label: "Method", render: (r) => r.Method },
              { key: "precision", label: "Precision", numeric: true, render: (r) => pct(r.precision) },
              { key: "recall", label: "Recall", numeric: true, render: (r) => pct(r.recall) },
              { key: "f1", label: "F1", numeric: true, render: (r) => decimal(r.f1, 3) },
              { key: "decisions", label: "Trips judged", numeric: true, render: (r) => count(r.decisions) },
            ]}
          />
        }
        source={source}
      />
      <Dispatcher data={data.dispatcher} source={source} />
      <Definitions text={data.definitions} />
    </>
  );
}

export function EarlyWarningView({ meta, initial }: { meta: Meta; initial: Initial<EarlyWarning> }) {
  return (
    <ModeDayView<EarlyWarning>
      meta={meta}
      page="early-warning"
      schema={earlyWarning}
      initial={initial}
      withDay={false}
      render={({ data, source }) => <Body data={data} source={source} />}
    />
  );
}
