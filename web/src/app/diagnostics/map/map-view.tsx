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
  const params = new URLSearchParams({ mode, route: row[col.route_id] as string, stop: `${dir ?? "-"}:${row[col.stop_id]}` });
  return `/diagnostics/stops/?${params.toString()}`;
}

/** The background is fetched once per visit, only when the map page is opened. */
let backgroundRequest: Promise<MapBackground> | null = null;
function loadBackground(): Promise<MapBackground> {
  backgroundRequest ??= fetch(BASEMAP_URL)
    .then((response) => {
      if (!response.ok) throw new Error(`${BASEMAP_URL}: HTTP ${response.status}`);
      return response.json();
    })
    .then((body) => basemap.parse(body))
    .catch((error) => {
      backgroundRequest = null; // let a later visit retry
      throw error;
    });
  return backgroundRequest;
}

/** How to read the map: every encoding and every line of the tooltip, in words. */
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
    <section aria-labelledby="map-key" className="mt-4 border border-rule bg-paper p-4 text-sm text-ink" data-testid="map-key">
      <h3 id="map-key" className="font-display text-lg">
        How to read this map
      </h3>
      <div className="mt-3 grid gap-6 lg:grid-cols-2">
        <dl className="grid grid-cols-[4.5rem_1fr] items-center gap-x-3 gap-y-3">
          <dt aria-hidden="true">
            <span className="block h-2.5 w-[4.5rem]" style={{ background: ramp }} />
          </dt>
          <dd className="text-muted-ink">
            <b className="font-semibold text-ink">Colour</b>: share of the stop&apos;s arrivals that were on time (at
            most 1 min early, at most 5 min late), from 0 % (palest) to 100 % (darkest).
          </dd>
          <dt aria-hidden="true">
            <svg width="72" height="16" viewBox="0 0 72 16">
              <g>{dot(MAP_SIZES[1])}</g>
              <g transform="translate(20 0)">{dot(MAP_SIZES[3])}</g>
              <g transform="translate(44 0)">{dot(MAP_SIZES[4])}</g>
            </svg>
          </dt>
          <dd className="text-muted-ink">
            <b className="font-semibold text-ink">Size</b>: how many arrivals were observed there, all routes and both
            days (about 130, 500 and 1,000 or more).
          </dd>
          <dt aria-hidden="true">
            <svg width="16" height="16" viewBox="0 0 16 16">
              {dot(MAP_SIZES[2], true)}
            </svg>
          </dt>
          <dd className="text-muted-ink">
            <b className="font-semibold text-ink">Hollow grey</b>: fewer than {count(minEvents)} arrivals, too few to
            score. Shown so the network stays complete.
          </dd>
          <dt aria-hidden="true">
            <svg width="72" height="16" viewBox="0 0 72 16">
              <path d="M2 5 H70" stroke={COLORS.rule} strokeWidth="1.5" />
              <path d="M2 11 H70" stroke={COLORS.muted} strokeWidth="2" opacity="0.6" />
            </svg>
          </dt>
          <dd className="text-muted-ink">
            <b className="font-semibold text-ink">Thin grey lines</b>: bus routes, which trace the streets (shown once you
            zoom in on bus stops). <b className="font-semibold text-ink">Darker lines</b>: subway lines. Both come from the
            MTA timetables.
          </dd>
        </dl>
        <div>
          <p className="font-medium">What a stop&apos;s tooltip says</p>
          <ol className="mt-2 space-y-1.5 text-muted-ink">
            <li>
              <b className="font-semibold text-ink">Name</b>: the stop&apos;s name in the MTA timetable.
            </li>
            <li>
              <b className="font-semibold text-ink">Stop ID</b>: its MTA identifier. Each direction of a street has its own
              stop and ID.
            </li>
            <li>
              <b className="font-semibold text-ink">Arrivals observed</b>: arrivals inferred from the real-time feed at the
              stop, every route that serves it, both service days pooled.
            </li>
            <li>
              <b className="font-semibold text-ink">On time</b>: the share of those arrivals within the on-time band. Click
              the stop to see it hour by hour.
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
    // Keep the visitor's zoom and pan when a layer changes; start from the whole city otherwise.
    const current = chart.current?.getOption() as { geo?: View[] } | undefined;
    const view = resetView.current ? undefined : current?.geo?.[0];
    resetView.current = false;
    return stopMapOption(stops, background, layers, showStreets, data.min_events, view && { center: view.center, zoom: view.zoom });
  }, [stops, background, layers, showStreets, data.min_events]);

  const onReady = useCallback((instance: EChartsType) => {
    chart.current = instance;
    // Track the zoom from the roam deltas (reading the whole option on every wheel step is slow).
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
    // Redraw even when the layers did not change (the build function is the same).
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

  // The rows arrive least reliable first (sufficient stops), then the thinly observed ones.
  const needle = query.trim().toLowerCase();
  const listed = (needle ? rows.filter((r) => (r[col.label] as string).toLowerCase().includes(needle)) : rows).slice(0, SHOWN);
  const toggle = (key: keyof MapLayers, label: string) => (
    <label className="inline-flex min-h-11 cursor-pointer items-center gap-2">
      <input
        type="checkbox"
        className="size-4 accent-[var(--ink)]"
        checked={layers[key]}
        onChange={(e) => setLayers((l) => ({ ...l, [key]: e.target.checked }))}
      />
      {label}
    </label>
  );
  const button = "inline-flex min-h-11 min-w-11 items-center justify-center border border-rule bg-paper px-3 hover:bg-panel";
  return (
    <>
      <ChartFrame
        title="Every located stop, coloured by how often it was on time"
        lead={
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm" role="group" aria-label="Map layers and view">
            {toggle("streets", "Streets (bus routes)")}
            {toggle("subway", "Subway lines")}
            {toggle("lineColors", "MTA line colours")}
            <span className="inline-flex gap-1">
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
          <>
            <p>
              Solid dots: stops with at least {data.min_events} arrivals over both days ({count(data.sufficient)}); hollow grey
              dots: fewer. Scroll or pinch to zoom, drag to move, click a stop to open its hour-by-hour reliability.
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
      // A new key per mode: other stops, so the map starts again from the whole city.
      render={({ data, source, mode }) => <Body key={mode} data={data} source={source} mode={mode} />}
    />
  );
}
