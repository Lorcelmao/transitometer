"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useMemo, useState } from "react";

import { EChart } from "@/charts/echart";
import { stopMapOption, type MapStop } from "@/charts/options";
import { ModeDayView } from "@/components/site/mode-day-view";
import { ChartFrame } from "@/components/story/chart-frame";
import { MAP_COLUMNS, stopMap, type Meta, type StopMap } from "@/data/schemas";
import type { Initial } from "@/hooks/use-view";
import { count } from "@/lib/format";

const col = Object.fromEntries(MAP_COLUMNS.map((c, i) => [c, i])) as Record<(typeof MAP_COLUMNS)[number], number>;
const SHOWN = 50;

type Row = StopMap["stops"][number];

function explorerHref(mode: string, row: Row) {
  const dir = row[col.direction_id];
  const params = new URLSearchParams({ mode, route: row[col.route_id] as string, stop: `${dir ?? "-"}:${row[col.stop_id]}` });
  return `/diagnostics/stops/?${params.toString()}`;
}

function Body({ data, source, mode }: { data: StopMap; source: Initial<StopMap>["source"]; mode: string }) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const rows = data.stops;
  const stops: MapStop[] = useMemo(
    () =>
      rows.map((r) => ({
        stopId: r[col.stop_id] as string,
        label: r[col.label] as string,
        lat: r[col.lat] as number,
        lon: r[col.lon] as number,
        events: r[col.events] as number,
        share: r[col.on_time_share] as number,
        display: r[col.display] as string,
        sufficient: r[col.sufficient] as boolean,
      })),
    [rows],
  );
  const byId = useMemo(() => new Map(rows.map((r) => [r[col.stop_id] as string, r])), [rows]);
  const build = useCallback((font: string) => stopMapOption(stops, font), [stops]);
  const open = useCallback(
    (item: unknown) => {
      const stop = (item as { stop?: MapStop }).stop;
      const row = stop && byId.get(stop.stopId);
      if (row) router.push(explorerHref(mode, row));
    },
    [byId, mode, router],
  );
  // The rows arrive least reliable first (sufficient stops), then the thinly observed ones.
  const needle = query.trim().toLowerCase();
  const listed = (needle ? rows.filter((r) => (r[col.label] as string).toLowerCase().includes(needle)) : rows).slice(0, SHOWN);
  return (
    <ChartFrame
      title="Every located stop, coloured by how often it was on time"
      summary={data.summary}
      chart={
        <EChart
          build={build}
          aspectRatio="1 / 1"
          renderer="canvas"
          label="Map of stops coloured by on-time share"
          onPointClick={open}
        />
      }
      table={
        <div>
          <label className="mb-3 flex max-w-md flex-col gap-1 text-sm">
            <span className="text-xs font-medium uppercase tracking-widest text-muted-ink">Find a stop</span>
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="min-h-11 border border-rule bg-paper px-3"
              placeholder="Stop name or id"
            />
          </label>
          <div className="max-h-[32rem] overflow-auto border-y border-rule" tabIndex={0} role="region" aria-label="Stops, least reliable first">
            <table className="w-full text-sm">
              <caption className="sr-only">Stops, least reliable first</caption>
              <thead className="sticky top-0 bg-panel">
                <tr>
                  {["Stop", "Arrivals", "On time", "Busiest route"].map((h, i) => (
                    <th key={h} scope="col" className={`px-3 py-2 text-xs font-medium uppercase tracking-wider text-muted-ink ${i ? "text-right" : "text-left"}`}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {listed.map((r) => (
                  <tr key={r[col.stop_id] as string} className="border-t border-rule/60">
                    <th scope="row" className="px-3 py-1.5 text-left font-medium">
                      <Link href={explorerHref(mode, r)}>{r[col.label]}</Link>
                    </th>
                    <td className="num px-3 py-1.5 text-right">{count(r[col.events] as number)}</td>
                    <td className="num px-3 py-1.5 text-right">
                      {r[col.display]}
                      {r[col.sufficient] ? "" : " (too few)"}
                    </td>
                    <td className="num px-3 py-1.5 text-right">{r[col.route_id]}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-muted-ink">
            Showing {listed.length} of {needle ? "the matching" : count(rows.length)} stops, least reliable first.
          </p>
        </div>
      }
      note={
        <p>
          Solid dots: stops with at least {data.min_events} arrivals over both days ({count(data.sufficient)}); hollow grey
          dots: fewer. Click a stop to open its hour-by-hour reliability.
        </p>
      }
      source={source}
    />
  );
}

export function MapView({ meta, initial }: { meta: Meta; initial: Initial<StopMap> }) {
  return (
    <ModeDayView<StopMap>
      meta={meta}
      page="map"
      schema={stopMap}
      initial={initial}
      withDay={false}
      render={({ data, source, mode }) => <Body data={data} source={source} mode={mode} />}
    />
  );
}
