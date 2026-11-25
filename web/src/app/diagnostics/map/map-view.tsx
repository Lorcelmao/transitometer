"use client";

import type { EChartsType } from "echarts/core";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { EChart } from "@/charts/echart";
import {
  MAP_SIZES,
  MAP_ZOOM_LIMIT,
  STREETS_FROM_ZOOM,
  stopMapOption,
  type MapBackground,
  type MapLayers,
  type MapStop,
} from "@/charts/options";
import { COLORS } from "@/charts/theme";
import { ModeDayView } from "@/components/site/mode-day-view";
import { ChartFrame } from "@/components/story/chart-frame";
import { Definitions } from "@/components/story/page-parts";
import { basemap, MAP_COLUMNS, stopMap, type Meta, type StopMap } from "@/data/schemas";
import type { Initial } from "@/hooks/use-view";
import { count } from "@/lib/format";

const col = Object.fromEntries(MAP_COLUMNS.map((c, i) => [c, i])) as Record<(typeof MAP_COLUMNS)[number], number>;
const SHOWN = 50;
const BASEMAP_URL = "/basemap/nyc.json";
const ZOOM_STEP = 1.6;

type Row = StopMap["stops"][number];
type View = { center?: number[]; zoom?: number };

function explorerHref(mode: string, row: Row) {
  const dir = row[col.direction_id];
  const params = new URLSearchParams({
    mode,
    route: row[col.route_id] as string,
    stop: `${dir ?? "-"}:${row[col.stop_id]}`,
  });
  return `/diagnostics/stops/?${params.toString()}`;
}

let backgroundRequest: Promise<MapBackground> | null = null;
function loadBackground(): Promise<MapBackground> {
  backgroundRequest ??= fetch(BASEMAP_URL)
    .then((response) => {
      if (!response.ok) throw new Error(`${BASEMAP_URL}: HTTP ${response.status}`);
      return response.json();
    })
    .then((body) => basemap.parse(body))
    .catch((error) => {
      backgroundRequest = null;
      throw error;
    });
  return backgroundRequest;
}

function MapKey({ minEvents }: { minEvents: number }) {
  const ramp = `linear-gradient(90deg, ${COLORS.sequential.join(", ")})`;
  const dot = (d: number, hollow = false) => (
    <circle
      cx={d / 2 + 1}
      cy={8}
      r={d / 2}
      fill={hollow ? "none" : COLORS.sequential[2]}
      stroke={hollow ? COLORS.thin : "none"}
      strokeWidth={1.5}
    />
  );
  return (
    <section
      aria-labelledby="map-key"
      className="mt-3 rounded-lg border border-rule bg-surface p-4 text-xs text-ink"
      data-testid="map-key"
    >
      <h3 id="map-key" className="text-sm font-semibold text-ink">
        How to read this map
      </h3>
      <div className="mt-3 grid gap-5 lg:grid-cols-2">
        <dl className="grid grid-cols-[4.5rem_1fr] items-center gap-x-3 gap-y-2.5">
          <dt aria-hidden="true">
            <span className="block h-2.5 w-[4.5rem] rounded-full" style={{ background: ramp }} />
          </dt>
          <dd className="text-muted-ink">
            <strong className="font-semibold text-ink">Colour:</strong> share of the stop&apos;s arrivals that were on
            time (at most 1 min early, at most 5 min late), from 0 % (palest) to 100 % (darkest).
          </dd>
          <dt aria-hidden="true">
            <svg width="72" height="16" viewBox="0 0 72 16">
              <g>{dot(MAP_SIZES[1])}</g>
              <g transform="translate(20 0)">{dot(MAP_SIZES[3])}</g>
              <g transform="translate(44 0)">{dot(MAP_SIZES[4])}</g>
            </svg>
          </dt>
          <dd className="text-muted-ink">
            <strong className="font-semibold text-ink">Size:</strong> arrivals observed there across all routes and
            both days (about 130, 500 and 1,000 or more).
          </dd>
          <dt aria-hidden="true">
            <svg width="16" height="16" viewBox="0 0 16 16">
              {dot(MAP_SIZES[2], true)}
            </svg>
          </dt>
          <dd className="text-muted-ink">
            <strong className="font-semibold text-ink">Hollow grey:</strong> fewer than {count(minEvents)} arrivals,
            too few to score. Shown so the network stays complete.
          </dd>
          <dt aria-hidden="true">
            <svg width="72" height="16" viewBox="0 0 72 16">
              <path d="M2 5 H70" stroke={COLORS.rule} strokeWidth="1.5" />
              <path d="M2 11 H70" stroke={COLORS.muted} strokeWidth="2" opacity="0.6" />
            </svg>
          </dt>
          <dd className="text-muted-ink">
            <strong className="font-semibold text-ink">Thin grey lines:</strong> bus routes (shown once you zoom in).{" "}
            <strong className="font-semibold text-ink">Darker lines:</strong> subway lines, from MTA timetables.
          </dd>
        </dl>
        <div>
          <p className="font-semibold text-ink">What a stop&apos;s tooltip says</p>
          <ol className="mt-2 space-y-1.5 text-muted-ink">
            <li>
              <strong className="font-semibold text-ink">Name:</strong> the stop&apos;s name in the MTA timetable.
            </li>
            <li>
              <strong className="font-semibold text-ink">Stop ID:</strong> its MTA identifier. Each direction of a
              street has its own stop and ID.
            </li>
            <li>
              <strong className="font-semibold text-ink">Arrivals observed:</strong> inferred arrivals at the stop,
              every route serving it, both service days pooled.
            </li>
            <li>
              <strong className="font-semibold text-ink">On time:</strong> share of arrivals within the on-time band.
              Click any stop to see it hour by hour.
            </li>
          </ol>
        </div>
      </div>
    </section>
  );
}

function Body({ data, source, mode }: { data: StopMap; source: Initial<StopMap>["source"]; mode: string }) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [layers, setLayers] = useState<MapLayers>({ streets: true, subway: true, lineColors: false });
  const [background, setBackground] = useState<MapBackground | null>(null);
  const [backgroundError, setBackgroundError] = useState(false);
  const [zoomedIn, setZoomedIn] = useState(false);
  const chart = useRef<EChartsType | null>(null);
  const zoom = useRef(1);
  const resetView = useRef(true);
  const rows = data.stops;

  useEffect(() => {
    let live = true;
    loadBackground().then(
      (b) => live && setBackground(b),
      () => live && setBackgroundError(true),
    );
    return () => {
      live = false;
    };
  }, []);

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
  const showStreets = mode !== "bus" || zoomedIn;
  const build = useCallback(() => {
    const current = chart.current?.getOption() as { geo?: View[] } | undefined;
    const view = resetView.current ? undefined : current?.geo?.[0];
    resetView.current = false;
    return stopMapOption(
      stops,
      background,
      layers,
      showStreets,
      data.min_events,
      view && { center: view.center, zoom: view.zoom },
    );
  }, [stops, background, layers, showStreets, data.min_events]);

  const onReady = useCallback((instance: EChartsType) => {
    chart.current = instance;
    instance.on("georoam", (event) => {
      const step = (event as { zoom?: number }).zoom;
      if (!step) return;
      zoom.current = Math.min(MAP_ZOOM_LIMIT.max, Math.max(MAP_ZOOM_LIMIT.min, zoom.current * step));
      setZoomedIn(zoom.current >= STREETS_FROM_ZOOM);
    });
  }, []);

  const zoomBy = (factor: number) => {
    const instance = chart.current;
    if (!instance) return;
    instance.dispatchAction({
      type: "geoRoam",
      componentType: "geo",
      geoIndex: 0,
      zoom: factor,
      originX: instance.getWidth() / 2,
      originY: instance.getHeight() / 2,
    });
  };
  const reset = () => {
    resetView.current = true;
    zoom.current = 1;
    setZoomedIn(false);
    setLayers((l) => ({ ...l }));
  };

  const open = useCallback(
    (item: unknown) => {
      const stop = Array.isArray(item) ? stops[item[2] as number] : undefined;
      const row = stop && rows.find((r) => r[col.stop_id] === stop.stopId);
      if (row) router.push(explorerHref(mode, row));
    },
    [stops, rows, mode, router],
  );

  const needle = query.trim().toLowerCase();
  const listed = (needle ? rows.filter((r) => (r[col.label] as string).toLowerCase().includes(needle)) : rows).slice(
    0,
    SHOWN,
  );
  const toggle = (key: keyof MapLayers, label: string) => (
    <label className="inline-flex min-h-10 cursor-pointer items-center gap-2 text-ink">
      <input
        type="checkbox"
        className="size-4 accent-brand"
        checked={layers[key]}
        onChange={(e) => setLayers((l) => ({ ...l, [key]: e.target.checked }))}
      />
      <span>{label}</span>
    </label>
  );
  const button =
    "inline-flex min-h-10 min-w-10 items-center justify-center rounded-md border border-rule bg-paper px-3 text-sm font-medium text-ink transition-colors hover:bg-panel";
  return (
    <>
      <ChartFrame
        title="Every located stop, coloured by how often it was on time"
        lead={
          <div className="mt-1 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm" role="group" aria-label="Map layers and view">
            {toggle("streets", "Streets (bus routes)")}
            {toggle("subway", "Subway lines")}
            {toggle("lineColors", "MTA line colours")}
            <span className="inline-flex gap-1.5">
              <button type="button" className={button} onClick={() => zoomBy(ZOOM_STEP)} aria-label="Zoom in">
                +
              </button>
              <button type="button" className={button} onClick={() => zoomBy(1 / ZOOM_STEP)} aria-label="Zoom out">
                −
              </button>
              <button type="button" className={button} onClick={reset}>
                Whole city
              </button>
            </span>
            <span className="text-xs text-muted-ink" aria-live="polite">
              {backgroundError
                ? "The background could not be loaded; the stops are shown alone."
                : layers.streets && !showStreets
                  ? "Zoom in to see the streets."
                  : ""}
            </span>
          </div>
        }
        summary={data.summary}
        chart={
          <EChart
            build={build}
            aspectRatio="1 / 1"
            renderer="canvas"
            label="Map of stops coloured by on-time share, over the bus and subway route network"
            onPointClick={open}
            onReady={onReady}
          />
        }
        table={
          <div>
            <label className="mb-3 flex max-w-md flex-col gap-1 text-sm">
              <span className="text-xs font-semibold text-muted-ink">Find a stop</span>
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="min-h-11 rounded-lg border border-rule-strong bg-surface px-3 text-sm"
                placeholder="Stop name or id"
              />
            </label>
            <div
              className="max-h-[30rem] max-w-full overflow-auto rounded-lg border border-rule bg-surface"
              tabIndex={0}
              role="region"
              aria-label="Stops, least reliable first"
            >
              <table className="w-full border-collapse text-sm">
                <caption className="sr-only">Stops, least reliable first</caption>
                <thead className="sticky top-0 bg-paper">
                  <tr>
                    {["Stop", "Arrivals", "On time", "Busiest route"].map((h, i) => (
                      <th
                        key={h}
                        scope="col"
                        className={`border-b border-rule px-3 py-2 text-xs font-semibold text-muted-ink ${
                          i ? "text-right" : "text-left"
                        }`}
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {listed.map((r) => (
                    <tr key={r[col.stop_id] as string} className="border-t border-panel hover:bg-paper/70">
                      <th scope="row" className="px-3 py-2 text-left font-medium">
                        <Link href={explorerHref(mode, r)} prefetch={false}>
                  {r[col.label]}
                </Link>
                      </th>
                      <td className="num px-3 py-2 text-right">{count(r[col.events] as number)}</td>
                      <td className="num px-3 py-2 text-right">
                        {r[col.display]}
                        {r[col.sufficient] ? "" : " (too few)"}
                      </td>
                      <td className="num px-3 py-2 text-right">{r[col.route_id]}</td>
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
          <>
            <p>
              Solid dots: stops with at least {data.min_events} arrivals over both days ({count(data.sufficient)});
              hollow grey dots: fewer. Scroll or pinch to zoom, drag to move, click a stop to open its hour-by-hour
              reliability.
            </p>
            <MapKey minEvents={data.min_events} />
          </>
        }
        source={source}
      />
      <Definitions text={data.definitions} />
    </>
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
      render={({ data, source, mode }) => <Body key={mode} data={data} source={source} mode={mode} />}
    />
  );
}
