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
  if (!data.segments.length) return <p className="my-10">No segment was observed often enough to be ranked.</p>;
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
              note: `typically ${seconds(s.median_excess_s)} over the timetable · ${count(s.segments)} observations`,
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
  if (!data.summary) return <p className="my-10">No trips were observed on this day.</p>;
  const shown = Object.fromEntries(data.figures.map((f) => [f.key, f.display]));
  return (
    <>
      <p className="max-w-3xl font-display text-2xl leading-snug md:text-3xl" data-testid="headline">
        A typical trip reached its first observed stop <span className="num">{shown.inherited}</span> late and
        lost another <span className="num">{shown.gained}</span> along the way, finishing{" "}
        <span className="num">{shown.final}</span> late.
      </p>
      <div className="mt-8">
        <KpiRow figures={data.figures} size="md" />
      </div>
      {data.caption ? <p className="mt-4 text-sm text-muted-ink">{data.caption}</p> : null}
      <SegmentList mode={mode} initial={segments} />
      <Definitions text={data.definitions} />
    </>
  );
}

export function DelayView({ meta, initial, segments }: { meta: Meta; initial: Initial<Delay>; segments: Initial<Segments> }) {
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
