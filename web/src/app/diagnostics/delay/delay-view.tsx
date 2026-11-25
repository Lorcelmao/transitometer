"use client";

import { ModeDayView } from "@/components/site/mode-day-view";
import { PairedBars } from "@/components/story/bar-list";
import { ChartFrame, DataTable } from "@/components/story/chart-frame";
import { KpiRow } from "@/components/story/kpi-figure";
import { Definitions } from "@/components/story/page-parts";
import { delay, segments as segmentsSchema, type Delay, type Meta, type Segments } from "@/data/schemas";
import { useView, type Initial } from "@/hooks/use-view";
import { count, seconds } from "@/lib/format";

function SegmentList({ mode, initial }: { mode: string; initial: Initial<Segments> }) {
  const { data, source, pending } = useView<Segments>(`delay/${mode}-segments.json`, segmentsSchema, initial);
  if (!data.segments.length) {
    return (
      <p className="my-6 rounded-xl border border-rule bg-surface p-5 text-sm text-muted-ink">
        No segment was observed often enough to be ranked.
      </p>
    );
  }
  const scale = Math.max(...data.segments.map((s) => Math.max(s.sched_travel_s, s.p50_travel_s)));
  return (
    <div className={pending ? "opacity-60" : ""}>
      <ChartFrame
        title="Stop-to-stop segments that lose the most time"
        summary={`Scheduled versus typical (median) travel time for the ${data.segments.length} segment-hours that lose the most time against the timetable. ${data.caption}`}
        chart={
          <PairedBars
            label="Scheduled and typical travel time by segment"
            legend={["Scheduled", "Typical (median)"]}
            scaleMax={scale}
            rows={data.segments.map((s) => ({
              key: `${s.route_id}-${s.from_stop}-${s.to_stop}-${s.service_hour}`,
              label: s.segment,
              note: `Typically ${seconds(s.median_excess_s)} over the timetable (${count(s.segments)} observations)`,
              a: s.sched_travel_s,
              aDisplay: seconds(s.sched_travel_s),
              b: s.p50_travel_s,
              bDisplay: seconds(s.p50_travel_s),
            }))}
          />
        }
        table={
          <DataTable
            caption="Segments that lose the most time"
            rows={data.segments}
            rowKey={(s) => `${s.route_id}-${s.from_stop}-${s.to_stop}-${s.service_hour}`}
            columns={[
              { key: "segment", label: "Segment", render: (s) => s.segment },
              { key: "n", label: "Observations", numeric: true, render: (s) => count(s.segments) },
              { key: "sched", label: "Scheduled", numeric: true, render: (s) => seconds(s.sched_travel_s) },
              { key: "p50", label: "Typical", numeric: true, render: (s) => seconds(s.p50_travel_s) },
              { key: "p90", label: "Bad day (p90)", numeric: true, render: (s) => seconds(s.p90_travel_s) },
              { key: "excess", label: "Typical excess", numeric: true, render: (s) => seconds(s.median_excess_s) },
            ]}
          />
        }
        source={source}
      />
    </div>
  );
}

function Body({ data, mode, segments }: { data: Delay; mode: string; segments: Initial<Segments> }) {
  if (!data.summary) {
    return (
      <p className="my-6 rounded-xl border border-rule bg-surface p-5 text-sm text-muted-ink">
        No trips were observed on this day.
      </p>
    );
  }
  return (
    <div className="space-y-5">
      {data.takeaway ? (
        <p
          className="rounded-lg border border-blue-200 border-l-4 border-l-brand bg-brand-soft px-4 py-3 text-[15px] leading-relaxed text-ink tabular-nums"
          data-testid="headline"
        >
          <strong className="font-semibold">Delay split:</strong> {data.takeaway}
        </p>
      ) : null}
      <KpiRow figures={data.figures} size="md" />
      {data.caption ? <p className="text-xs text-muted-ink">{data.caption}</p> : null}
      <SegmentList mode={mode} initial={segments} />
      <Definitions text={data.definitions} />
    </div>
  );
}

export function DelayView({
  meta,
  initial,
  segments,
}: {
  meta: Meta;
  initial: Initial<Delay>;
  segments: Initial<Segments>;
}) {
  return (
    <ModeDayView<Delay>
      meta={meta}
      page="delay"
      schema={delay}
      initial={initial}
      render={({ data, mode }) => <Body data={data} mode={mode} segments={segments} />}
    />
  );
}
