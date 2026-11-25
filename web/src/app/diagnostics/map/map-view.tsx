"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  bandMeta,
  gridTooltip,
  indexStreets,
  LOD_ZOOM_THRESHOLD,
  MAP_DIVERGING_BANDS,
  MAP_ZOOM_LIMIT,
  NYC_INITIAL_ZOOM,
  splitLabel,
  stopTooltip,
  STREETS_FROM_ZOOM,
  type BandFilter,
  type Bbox,
  type MapGridCell,
  type MapLayers,
  type MapStop,
  type StreetPolyline,
  type SubwayLineGroup,
} from "@/charts/options";
import { StopMapCanvas, type GeoJsonCollection } from "@/charts/stop-map-canvas";
import { COLORS } from "@/charts/theme";
import { ModeToggle } from "@/components/site/filters";
import { ProvenanceLine } from "@/components/site/provenance-line";
import { Definitions } from "@/components/story/page-parts";
import { MAP_COLUMNS, type MapStopRow } from "@/data/map-columns";
import type { MapTileSpec, Meta, Source, StopMapGrid } from "@/data/schemas";
import { useUrlState } from "@/hooks/use-url-state";
import { count } from "@/lib/format";

const col = Object.fromEntries(MAP_COLUMNS.map((c, i) => [c, i])) as Record<
  (typeof MAP_COLUMNS)[number],
  number
>;
const TABLE_LIMIT = 50;
const ZOOM_STEP = 1.6;
const NYC_BOROUGHS_URL = "/basemap/nyc-boroughs.geojson";
const NYC_SUBWAY_URL = "/basemap/nyc-subway.json";
const NYC_STREETS_URL = "/basemap/nyc-streets.json";
const NYC_BOROUGHS_DATE = "2026-11-25";
const NYC_BOROUGHS_SHA256 = "e79e5c1277d08ba99c8a220d50b71c1c25d2ff667e68c8d1368041c89c62e33d";

function rowToStop(r: MapStopRow): MapStop {
  return {
    stopId: r[col.stop_id] as string,
    label: r[col.label] as string,
    lat: r[col.lat] as number,
    lon: r[col.lon] as number,
    events: r[col.events] as number,
    share: r[col.on_time_share] as number,
    display: r[col.display] as string,
    sufficient: r[col.sufficient] as boolean,
    routeId: r[col.route_id] as string,
    directionId: r[col.direction_id] as number | null,
  };
}

function explorerHref(mode: string, stop: Pick<MapStop, "directionId" | "routeId" | "stopId">) {
  const params = new URLSearchParams({
    mode,
    route: stop.routeId,
    stop: `${stop.directionId ?? "-"}:${stop.stopId}`,
  });
  return `/diagnostics/stops/?${params.toString()}`;
}

function nextFrame(): Promise<void> {
  return new Promise((resolve) => requestAnimationFrame(() => resolve()));
}

let boroughsPromise: Promise<GeoJsonCollection> | null = null;
function loadBoroughs(): Promise<GeoJsonCollection> {
  boroughsPromise ??= fetch(NYC_BOROUGHS_URL)
    .then((r) => {
      if (!r.ok) throw new Error(`${NYC_BOROUGHS_URL}: HTTP ${r.status}`);
      return r.json();
    })
    .catch((err) => {
      boroughsPromise = null;
      throw err;
    });
  return boroughsPromise;
}

let subwayLinesPromise: Promise<SubwayLineGroup[]> | null = null;
function loadSubwayLines(): Promise<SubwayLineGroup[]> {
  subwayLinesPromise ??= fetch(NYC_SUBWAY_URL)
    .then((r) => {
      if (!r.ok) throw new Error(`${NYC_SUBWAY_URL}: HTTP ${r.status}`);
      return r.json();
    })
    .then((body: { subway?: SubwayLineGroup[] }) => body.subway ?? [])
    .catch((err) => {
      subwayLinesPromise = null;
      throw err;
    });
  return subwayLinesPromise;
}

let streetsPromise: Promise<StreetPolyline[]> | null = null;
function loadStreets(): Promise<StreetPolyline[]> {
  streetsPromise ??= fetch(NYC_STREETS_URL)
    .then((r) => {
      if (!r.ok) throw new Error(`${NYC_STREETS_URL}: HTTP ${r.status}`);
      return r.json();
    })
    .then((body: { streets?: [number, number][][] }) => indexStreets(body.streets ?? []))
    .catch((err) => {
      streetsPromise = null;
      throw err;
    });
  return streetsPromise;
}

const gridCache = new Map<string, Promise<StopMapGrid>>();
function loadGrid(mode: string): Promise<StopMapGrid> {
  const existing = gridCache.get(mode);
  if (existing) return existing;
  const p = fetch(`/data/map-grid/${mode}.json`)
    .then((r) => {
      if (!r.ok) throw new Error(`/data/map-grid/${mode}.json: HTTP ${r.status}`);
      return r.json();
    })
    .then((env: { data: StopMapGrid }) => env.data)
    .catch((err) => {
      gridCache.delete(mode);
      throw err;
    });
  gridCache.set(mode, p);
  return p;
}

const fullStopsCache = new Map<string, Promise<MapStop[]>>();
function loadFullStops(mode: string): Promise<MapStop[]> {
  const existing = fullStopsCache.get(mode);
  if (existing) return existing;
  const p = fetch(`/data/map/${mode}.json`)
    .then((r) => {
      if (!r.ok) throw new Error(`/data/map/${mode}.json: HTTP ${r.status}`);
      return r.json();
    })
    .then((env: { data: { stops: MapStopRow[] } }) => env.data.stops.map(rowToStop))
    .catch((err) => {
      fullStopsCache.delete(mode);
      throw err;
    });
  fullStopsCache.set(mode, p);
  return p;
}

const tileCache = new Map<string, MapStop[]>();
const tilePromises = new Map<string, Promise<MapStop[]>>();
function tilesForBbox(spec: MapTileSpec, bbox: Bbox | null): string[] {
  const available = new Set(spec.tiles);
  if (!bbox) return available.has("1-1") ? ["1-1"] : spec.tiles.slice(0, 1);
  const [minLon, maxLon, minLat, maxLat] = bbox;
  const lonSpan = spec.max_lon - spec.min_lon;
  const latSpan = spec.max_lat - spec.min_lat;
  const x0 = Math.max(0, Math.min(spec.n - 1, Math.floor(((minLon - spec.min_lon) / lonSpan) * spec.n)));
  const x1 = Math.max(0, Math.min(spec.n - 1, Math.floor(((maxLon - spec.min_lon) / lonSpan) * spec.n)));
  const y0 = Math.max(0, Math.min(spec.n - 1, Math.floor(((minLat - spec.min_lat) / latSpan) * spec.n)));
  const y1 = Math.max(0, Math.min(spec.n - 1, Math.floor(((maxLat - spec.min_lat) / latSpan) * spec.n)));
  const keys: string[] = [];
  for (let x = x0; x <= x1; x++) {
    for (let y = y0; y <= y1; y++) {
      const k = `${x}-${y}`;
      if (available.has(k)) keys.push(k);
    }
  }
  return keys;
}

function ensureBusTiles(spec: MapTileSpec, bbox: Bbox | null): Promise<boolean> {
  const keys = tilesForBbox(spec, bbox);
  const pending: Promise<unknown>[] = [];
  for (const key of keys) {
    if (tileCache.has(key)) continue;
    let req = tilePromises.get(key);
    if (!req) {
      req = fetch(`/data/map-tiles/bus/t-${key}.json`)
        .then((r) => {
          if (!r.ok) throw new Error(`/data/map-tiles/bus/t-${key}.json: HTTP ${r.status}`);
          return r.json();
        })
        .then(async (env: { data: { stops: MapStopRow[] } }) => {
          await nextFrame();
          const parsed = env.data.stops.map(rowToStop);
          tileCache.set(key, parsed);
          return parsed;
        })
        .catch((err) => {
          tilePromises.delete(key);
          throw err;
        });
      tilePromises.set(key, req);
    }
    pending.push(req);
  }
  return pending.length ? Promise.all(pending).then(() => true) : Promise.resolve(false);
}

function loadedBusStopsForBbox(spec: MapTileSpec, bbox: Bbox | null, fullBus: MapStop[] | null): MapStop[] {
  if (fullBus) return fullBus;
  const out: MapStop[] = [];
  for (const key of tilesForBbox(spec, bbox)) {
    const rows = tileCache.get(key);
    if (rows) {
      for (let i = 0; i < rows.length; i++) out.push(rows[i]);
    }
  }
  return out;
}

export function MapView({
  meta,
  busInitial,
  subwayInitial,
  arrivalWeightedNote,
  source,
}: {
  meta: Meta;
  busInitial: StopMapGrid;
  subwayInitial: StopMapGrid;
  arrivalWeightedNote: string;
  source: Source;
}) {
  const modes = useMemo(() => meta.modes.map((m) => m.key), [meta.modes]);
  const [urlState, setUrlState] = useUrlState({ mode: modes[0] }, { mode: modes });
  const mode: "bus" | "subway" = urlState.mode === "subway" ? "subway" : "bus";

  const activeMeta = mode === "subway" ? subwayInitial : busInitial;
  const [asTable, setAsTable] = useState(false);
  const [filterBand, setFilterBand] = useState<BandFilter>(null);
  const [layers, setLayers] = useState<MapLayers>({ streets: true, subway: true, lineColors: false });
  const [selectedStop, setSelectedStop] = useState<{ mode: string; stop: MapStop } | null>(null);
  const [lodStatus, setLodStatus] = useState("670 m grid (1,502 cells). Zoom in for stops.");
  const [mapError, setMapError] = useState(false);

  const [searchQuery, setSearchQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchList, setSearchList] = useState<MapStop[] | null>(null);
  const [tableQuery, setTableQuery] = useState("");
  const [tableFullStops, setTableFullStops] = useState<MapStop[] | null>(null);

  const mapHostRef = useRef<HTMLDivElement | null>(null);
  const searchWrapRef = useRef<HTMLDivElement | null>(null);
  const engineRef = useRef<StopMapCanvas | null>(null);
  const fontRef = useRef("sans-serif");
  const modeRef = useRef<"bus" | "subway">(mode);
  const filterBandRef = useRef<BandFilter>(filterBand);
  const layersRef = useRef<MapLayers>(layers);
  const selectedRef = useRef<{ mode: string; stop: MapStop } | null>(selectedStop);
  const prevDetailOpenRef = useRef(false);
  const roamTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastStatusRef = useRef("670 m grid (1,502 cells). Zoom in for stops.");

  const busGridCellsRef = useRef<MapGridCell[]>([]);
  const subwayStopsRef = useRef<MapStop[] | null>(null);
  const fullBusStopsRef = useRef<MapStop[] | null>(null);
  const subwayLinesLoadedRef = useRef(false);
  const streetsRef = useRef<StreetPolyline[] | null>(null);
  const activeStopsRef = useRef<readonly MapStop[]>([]);

  useEffect(() => {
    modeRef.current = mode;
    filterBandRef.current = filterBand;
    layersRef.current = layers;
    selectedRef.current = selectedStop;
  }, [mode, filterBand, layers, selectedStop]);

  const syncEngine = useCallback(() => {
    const engine = engineRef.current;
    if (!engine) return;
    const curMode = modeRef.current;
    const z = engine.getZoom();
    const useGrid = curMode === "bus" && z < LOD_ZOOM_THRESHOLD;
    const bbox = curMode === "bus" && !useGrid ? engine.getViewportBbox(0.08) : null;

    const curStops: MapStop[] = useGrid
      ? []
      : curMode === "subway"
        ? subwayStopsRef.current ?? []
        : busInitial.tile_spec
          ? loadedBusStopsForBbox(busInitial.tile_spec, bbox, fullBusStopsRef.current)
          : [];
    activeStopsRef.current = curStops;

    const curSelected =
      selectedRef.current && selectedRef.current.mode === curMode
        ? { lon: selectedRef.current.stop.lon, lat: selectedRef.current.stop.lat }
        : null;

    engine.setState({
      mode: curMode,
      useGrid,
      gridCells: busGridCellsRef.current,
      stops: curStops,
      filterBand: filterBandRef.current,
      layers: layersRef.current,
      streets: streetsRef.current,
      selectedStop: curSelected,
      font: fontRef.current,
    });
  }, [busInitial.tile_spec]);

  const scheduleLazyAssets = useCallback(() => {
    if (roamTimerRef.current) clearTimeout(roamTimerRef.current);
    roamTimerRef.current = setTimeout(async () => {
      roamTimerRef.current = null;
      const engine = engineRef.current;
      if (!engine) return;
      const curMode = modeRef.current;
      const z = engine.getZoom();
      const compact = window.innerWidth <= 768;
      const streetZoomMin = compact ? 3.2 : STREETS_FROM_ZOOM;
      const pending: Promise<unknown>[] = [];
      let needsSync = false;

      if (curMode === "bus" && z >= LOD_ZOOM_THRESHOLD && busInitial.tile_spec) {
        const targetBbox = engine.getViewportBbox(0.1);
        pending.push(
          ensureBusTiles(busInitial.tile_spec, targetBbox).then((loadedNew) => {
            if (loadedNew) needsSync = true;
          }),
        );
        // Refresh visible stops for the current viewport tiles even if already cached.
        needsSync = true;
      }

      if (curMode === "bus" && layersRef.current.streets && z >= streetZoomMin && !streetsRef.current) {
        pending.push(
          loadStreets().then((s) => {
            streetsRef.current = s;
            needsSync = true;
          }),
        );
      }

      if (layersRef.current.subway && (curMode === "subway" || z >= STREETS_FROM_ZOOM) && !subwayLinesLoadedRef.current) {
        pending.push(
          loadSubwayLines().then((lines) => {
            subwayLinesLoadedRef.current = true;
            engineRef.current?.setSubwayLines(lines);
          }),
        );
      }

      if (pending.length) {
        await Promise.all(pending);
        await nextFrame();
      }
      if (needsSync && engineRef.current) {
        syncEngine();
      }
    }, 135);
  }, [busInitial.tile_spec, syncEngine]);

  // Initialise ONE persistent Canvas 2D map engine on mount.
  useEffect(() => {
    let disposed = false;
    const host = mapHostRef.current;
    if (!host) return;

    const styles = getComputedStyle(document.documentElement);
    const font = styles.getPropertyValue("--font-atkinson").trim() || "sans-serif";
    fontRef.current = font;

    const engine = new StopMapCanvas(host, {
      onViewChange: () => {
        scheduleLazyAssets();
      },
      onVisibleCount: (visibleCount, useGrid, z) => {
        const curMode = modeRef.current;
        const text = useGrid
          ? `670 m grid (${count(visibleCount)} cells). Zoom in for stops.`
          : curMode === "subway"
            ? `Subway stations (${count(visibleCount)} shown), zoom ${z.toFixed(1)}x.`
            : `Bus stops (${count(visibleCount)} in view), zoom ${z.toFixed(1)}x.`;
        if (text !== lastStatusRef.current) {
          lastStatusRef.current = text;
          setLodStatus(text);
        }
      },
      onClickGrid: (_index, cell) => {
        engineRef.current?.setView([cell[0], cell[1]], 4.2, true);
      },
      onClickStop: (_index, stop) => {
        setSelectedStop({ mode: modeRef.current, stop });
      },
      formatGridTooltip: (index) => {
        const cell = busGridCellsRef.current[index];
        return cell
          ? gridTooltip(cell, busInitial.stop_median_share, busInitial.stop_median_display, fontRef.current)
          : "";
      },
      formatStopTooltip: (index) => {
        const stop = activeStopsRef.current[index];
        if (!stop) return "";
        const curMode = modeRef.current;
        const mMeta = curMode === "subway" ? subwayInitial : busInitial;
        return stopTooltip(
          stop,
          mMeta.min_events,
          curMode === "subway" ? "subway" : "bus",
          mMeta.stop_median_share,
          mMeta.stop_median_display,
          fontRef.current,
        );
      },
    });
    engineRef.current = engine;

    const initPromises: Promise<unknown>[] = [
      loadBoroughs(),
      loadGrid("bus"),
    ];

    if (modeRef.current === "subway") {
      initPromises.push(loadGrid("subway"), loadSubwayLines());
    }

    Promise.all(initPromises)
      .then(([boroughs, busGrid, subGrid, subLines]) => {
        if (disposed) return;
        busGridCellsRef.current = (busGrid as StopMapGrid).grid_cells;
        if (subGrid) subwayStopsRef.current = (subGrid as StopMapGrid).stops.map(rowToStop);
        if (subLines) {
          subwayLinesLoadedRef.current = true;
          engine.setSubwayLines(subLines as SubwayLineGroup[]);
        }
        engine.setBoroughs(boroughs as GeoJsonCollection);
        syncEngine();
      })
      .catch(() => {
        if (!disposed) setMapError(true);
      });

    return () => {
      disposed = true;
      if (roamTimerRef.current) clearTimeout(roamTimerRef.current);
      engine.dispose();
      engineRef.current = null;
    };
    // Initialises once; subsequent filter/mode/layer updates reuse the single canvas instance.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-sync when mode switches (reusing the same canvas with zero re-init).
  useEffect(() => {
    let live = true;
    modeRef.current = mode;
    if (roamTimerRef.current) {
      clearTimeout(roamTimerRef.current);
      roamTimerRef.current = null;
    }

    async function applyMode() {
      const pending: Promise<unknown>[] = [];
      if (mode === "subway") {
        if (!subwayStopsRef.current) {
          pending.push(
            loadGrid("subway").then((subGrid) => {
              if (live) subwayStopsRef.current = subGrid.stops.map(rowToStop);
            }),
          );
        }
        if (!subwayLinesLoadedRef.current) {
          pending.push(
            loadSubwayLines().then((lines) => {
              if (live) {
                subwayLinesLoadedRef.current = true;
                engineRef.current?.setSubwayLines(lines);
              }
            }),
          );
        }
      } else if (
        engineRef.current &&
        engineRef.current.getZoom() >= LOD_ZOOM_THRESHOLD &&
        busInitial.tile_spec
      ) {
        pending.push(ensureBusTiles(busInitial.tile_spec, engineRef.current.getViewportBbox(0.08)));
      }
      if (pending.length) {
        await Promise.all(pending);
        if (!live) return;
      }
      if (live && engineRef.current) syncEngine();
    }
    applyMode();
    return () => {
      live = false;
    };
  }, [mode, busInitial.tile_spec, syncEngine]);

  // Re-sync when legend band filter, layer toggles, or pinned detail panel change.
  useEffect(() => {
    let live = true;
    filterBandRef.current = filterBand;
    layersRef.current = layers;
    selectedRef.current = selectedStop;
    const detailOpen = Boolean(selectedStop && selectedStop.mode === modeRef.current);
    const detailToggled = detailOpen !== prevDetailOpenRef.current;
    prevDetailOpenRef.current = detailOpen;

    async function applyChange() {
      const engine = engineRef.current;
      if (!engine) return;
      const compact = window.innerWidth <= 768;
      const streetZoomMin = compact ? 3.2 : STREETS_FROM_ZOOM;
      const z = engine.getZoom();
      if (modeRef.current === "bus" && layers.streets && z >= streetZoomMin && !streetsRef.current) {
        streetsRef.current = await loadStreets();
        if (!live) return;
      }
      if (layers.subway && (modeRef.current === "subway" || z >= STREETS_FROM_ZOOM) && !subwayLinesLoadedRef.current) {
        const lines = await loadSubwayLines();
        if (!live) return;
        subwayLinesLoadedRef.current = true;
        engine.setSubwayLines(lines);
      }
      if (live && engineRef.current) {
        if (detailToggled) engineRef.current.resize();
        syncEngine();
      }
    }
    applyChange();
    return () => {
      live = false;
    };
  }, [filterBand, layers, selectedStop, syncEngine]);

  useEffect(() => {
    if (!asTable && engineRef.current) {
      requestAnimationFrame(() => {
        engineRef.current?.resize();
        syncEngine();
      });
    }
  }, [asTable, syncEngine]);

  useEffect(() => {
    const onDocClick = (e: MouseEvent) => {
      if (searchWrapRef.current && !searchWrapRef.current.contains(e.target as Node)) {
        setSearchOpen(false);
      }
    };
    document.addEventListener("click", onDocClick);
    return () => document.removeEventListener("click", onDocClick);
  }, []);

  const handleModeChange = (nextMode: string) => {
    setSelectedStop(null);
    setSearchQuery("");
    setSearchOpen(false);
    setSearchList(null);
    setTableQuery("");
    setTableFullStops(null);
    setUrlState({ mode: nextMode });
  };

  const zoomBy = (factor: number) => {
    const engine = engineRef.current;
    if (!engine) return;
    const next = Math.min(
      MAP_ZOOM_LIMIT.max,
      Math.max(MAP_ZOOM_LIMIT.min, +(engine.getZoom() * factor).toFixed(2)),
    );
    engine.setView(null, next, true);
  };

  const resetCity = () => {
    const engine = engineRef.current;
    if (!engine) return;
    if (roamTimerRef.current) {
      clearTimeout(roamTimerRef.current);
      roamTimerRef.current = null;
    }
    engine.resetView();
    syncEngine();
  };

  const ensureSearchCorpus = useCallback(async () => {
    if (mode === "subway") {
      if (!subwayStopsRef.current) {
        const subGrid = await loadGrid("subway");
        subwayStopsRef.current = subGrid.stops.map(rowToStop);
      }
      setSearchList(subwayStopsRef.current);
      return;
    }
    if (!fullBusStopsRef.current) {
      fullBusStopsRef.current = await loadFullStops("bus");
    }
    setSearchList(fullBusStopsRef.current);
  }, [mode]);

  const jumpToStop = async (stop: MapStop) => {
    setSearchOpen(false);
    setSearchQuery(splitLabel(stop).name);
    if (asTable) setAsTable(false);
    if (roamTimerRef.current) {
      clearTimeout(roamTimerRef.current);
      roamTimerRef.current = null;
    }
    if (mode === "bus" && layers.streets && !streetsRef.current) {
      streetsRef.current = await loadStreets();
    }
    engineRef.current?.setView([stop.lon, stop.lat], 10, false);
    setSelectedStop({ mode, stop });
  };

  const searchHits = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (q.length < 2 || !searchList) return [];
    const out: MapStop[] = [];
    for (let i = 0; i < searchList.length; i++) {
      const s = searchList[i];
      if (
        s.label.toLowerCase().includes(q) ||
        s.stopId.toLowerCase().includes(q) ||
        s.routeId.toLowerCase().includes(q)
      ) {
        out.push(s);
        if (out.length >= 8) break;
      }
    }
    return out;
  }, [searchQuery, searchList]);

  const defaultWorstStops = useMemo(
    () => activeMeta.worst_rows.map(rowToStop),
    [activeMeta.worst_rows],
  );
  const tableRows = useMemo(() => {
    const q = tableQuery.trim().toLowerCase();
    if (!q) return defaultWorstStops.slice(0, TABLE_LIMIT);
    const pool = tableFullStops ?? defaultWorstStops;
    return pool
      .filter(
        (s) =>
          s.label.toLowerCase().includes(q) ||
          s.stopId.toLowerCase().includes(q) ||
          s.routeId.toLowerCase().includes(q),
      )
      .slice(0, TABLE_LIMIT);
  }, [defaultWorstStops, tableFullStops, tableQuery]);

  const handleTableSearch = (value: string) => {
    setTableQuery(value);
    if (value.trim().length >= 1 && !tableFullStops) {
      if (mode === "subway" && subwayStopsRef.current) {
        setTableFullStops(subwayStopsRef.current);
      } else {
        loadFullStops(mode).then((rows) => setTableFullStops(rows));
      }
    }
  };

  const toggleBand = (band: Exclude<BandFilter, null>) => {
    setFilterBand((prev) => (prev === band ? null : band));
  };

  const selectedDetail = selectedStop && selectedStop.mode === mode ? selectedStop.stop : null;
  const selectedSplit = selectedDetail ? splitLabel(selectedDetail) : null;
  const selectedBand = selectedDetail ? bandMeta(selectedDetail.share, selectedDetail.sufficient) : null;
  const selectedDelta =
    selectedDetail && selectedDetail.sufficient && activeMeta.stop_median_share !== null
      ? ((selectedDetail.share - activeMeta.stop_median_share) * 100).toFixed(1)
      : null;

  const btnCls =
    "inline-flex min-h-10 items-center justify-center rounded-md border border-rule-strong bg-surface px-3 text-xs font-semibold text-ink transition-colors hover:bg-panel";

  return (
    <div className="mt-4" data-testid="view">
      {/* Compact KPI summary strip above the fold */}
      <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3" aria-label="Mode summary">
        <div className="rounded-lg border border-rule bg-surface px-4 py-3 shadow-xs">
          <p className="text-xs font-medium text-muted-ink">Typical stop (equal-weighted median)</p>
          <p className="num mt-0.5 text-xl font-bold text-ink">{activeMeta.stop_median_display}</p>
          <p className="mt-0.5 text-xs text-muted-ink">
            Midpoint across scored {mode} stops (not the arrival-weighted system rate).
          </p>
        </div>
        <div className="rounded-lg border border-rule bg-surface px-4 py-3 shadow-xs">
          <p className="text-xs font-medium text-muted-ink">Critical stops (under 30 % on time)</p>
          <p className="num mt-0.5 text-xl font-bold text-fail">{count(activeMeta.band_counts[0] ?? 0)}</p>
          <p className="mt-0.5 text-xs text-muted-ink">
            {((100 * (activeMeta.band_counts[0] ?? 0)) / Math.max(1, activeMeta.sufficient)).toFixed(1)} % of scored{" "}
            {mode} stops.
          </p>
        </div>
        <div className="rounded-lg border border-rule bg-surface px-4 py-3 shadow-xs">
          <p className="text-xs font-medium text-muted-ink">Scored stops (at least {activeMeta.min_events} arrivals)</p>
          <p className="num mt-0.5 text-xl font-bold text-ink">{count(activeMeta.sufficient)}</p>
          <p className="mt-0.5 text-xs text-muted-ink">
            {count(activeMeta.total)} located total ({count(activeMeta.thin)} under {activeMeta.min_events} arrivals).
          </p>
        </div>
      </div>

      {/* Main map card */}
      <figure className="overflow-hidden rounded-xl border border-rule bg-surface shadow-xs">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-rule px-4 py-3">
          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-3">
            <ModeToggle modes={meta.modes} value={mode} onChange={handleModeChange} />

            <div ref={searchWrapRef} className="relative min-w-[220px] max-w-sm flex-1">
              <label htmlFor="map-stop-search" className="sr-only">
                Find a stop by name, stop ID, or route
              </label>
              <input
                id="map-stop-search"
                type="search"
                value={searchQuery}
                onFocus={() => {
                  ensureSearchCorpus();
                  if (searchQuery.trim().length >= 2) setSearchOpen(true);
                }}
                onChange={(e) => {
                  setSearchQuery(e.target.value);
                  setSearchOpen(e.target.value.trim().length >= 2);
                  if (!searchList) ensureSearchCorpus();
                }}
                placeholder="Find a stop, ID, or route (e.g. M4, Clark St)"
                autoComplete="off"
                className="min-h-10 w-full rounded-lg border border-rule-strong bg-surface px-3 text-sm text-ink placeholder:text-muted-ink"
              />
              {searchOpen && searchQuery.trim().length >= 2 ? (
                <ul
                  role="listbox"
                  aria-label="Matching stops"
                  className="absolute left-0 right-0 top-[calc(100%+4px)] z-40 max-h-72 overflow-y-auto rounded-lg border border-rule-strong bg-surface p-1 shadow-lg"
                >
                  {searchHits.length ? (
                    searchHits.map((stop) => {
                      const sp = splitLabel(stop);
                      const bm = bandMeta(stop.share, stop.sufficient);
                      return (
                        <li key={`${stop.stopId}-${stop.routeId}-${stop.directionId ?? "x"}`}>
                          <button
                            type="button"
                            onClick={() => jumpToStop(stop)}
                            className="flex w-full items-center justify-between gap-3 rounded-md px-2.5 py-2 text-left hover:bg-panel"
                          >
                            <span className="min-w-0">
                              <span className="block truncate text-xs font-semibold text-ink">{sp.name}</span>
                              <span className="num block text-[11px] text-muted-ink">
                                Stop {sp.id}, route {stop.routeId}
                              </span>
                            </span>
                            <span className="num shrink-0 text-xs font-bold" style={{ color: bm.color }}>
                              {stop.sufficient ? stop.display : "Not scored"}
                            </span>
                          </button>
                        </li>
                      );
                    })
                  ) : (
                    <li className="px-3 py-2 text-xs text-muted-ink">
                      {searchList ? "No matching stops found." : "Loading stop index..."}
                    </li>
                  )}
                </ul>
              ) : null}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            {mode === "bus" ? (
              <label className="inline-flex min-h-10 cursor-pointer items-center gap-2 text-xs font-medium text-ink">
                <input
                  type="checkbox"
                  className="size-6 cursor-pointer accent-brand"
                  checked={layers.streets}
                  onChange={(e) => setLayers((l) => ({ ...l, streets: e.target.checked }))}
                />
                <span>Streets (zoomed)</span>
              </label>
            ) : (
              <>
                <label className="inline-flex min-h-10 cursor-pointer items-center gap-2 text-xs font-medium text-ink">
                  <input
                    type="checkbox"
                    className="size-6 cursor-pointer accent-brand"
                    checked={layers.subway}
                    onChange={(e) => setLayers((l) => ({ ...l, subway: e.target.checked }))}
                  />
                  <span>Subway lines</span>
                </label>
                <label className="inline-flex min-h-10 cursor-pointer items-center gap-2 text-xs font-medium text-ink">
                  <input
                    type="checkbox"
                    className="size-6 cursor-pointer accent-brand"
                    checked={layers.lineColors}
                    onChange={(e) => setLayers((l) => ({ ...l, lineColors: e.target.checked }))}
                  />
                  <span>MTA line colours</span>
                </label>
              </>
            )}
            <button type="button" className={btnCls} onClick={resetCity}>
              Whole city
            </button>
            <button
              type="button"
              aria-pressed={asTable}
              onClick={() => setAsTable((v) => !v)}
              className="inline-flex min-h-10 items-center rounded-md border border-rule bg-paper px-3 text-xs font-semibold text-brand transition-colors hover:bg-brand-soft"
            >
              {asTable ? "Show as chart" : "Show as table"}
            </button>
          </div>
        </div>

        {/* Always-visible interactive diverging color scale directly above the map */}
        <div
          data-testid="map-key"
          aria-label="On-time share color scale"
          className="flex flex-col gap-2 border-b border-rule bg-paper/70 px-4 py-2.5"
        >
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="mr-1 text-xs font-semibold text-ink">On-time share</span>
            {MAP_DIVERGING_BANDS.map((band) => {
              const pressed = filterBand === band.id;
              return (
                <button
                  key={band.id}
                  type="button"
                  aria-pressed={pressed}
                  onClick={() => toggleBand(band.id)}
                  className={`inline-flex min-h-8 items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors ${
                    pressed
                      ? "border-ink bg-slate-200 font-semibold text-ink"
                      : "border-rule bg-surface text-ink hover:bg-panel"
                  }`}
                >
                  <span
                    className="inline-block size-2.5 shrink-0 rounded-full"
                    style={{ backgroundColor: band.color }}
                    aria-hidden="true"
                  />
                  <span>
                    {band.label} {band.range}
                  </span>
                </button>
              );
            })}
            <button
              type="button"
              aria-pressed={filterBand === "thin"}
              onClick={() => toggleBand("thin")}
              className={`inline-flex min-h-8 items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors ${
                filterBand === "thin"
                  ? "border-ink bg-slate-200 font-semibold text-ink"
                  : "border-rule bg-surface text-ink hover:bg-panel"
              }`}
            >
              <span
                className="inline-block size-2.5 shrink-0 rounded-full border-[1.5px] bg-surface"
                style={{ borderColor: COLORS.mapThinStroke }}
                aria-hidden="true"
              />
              <span>Under {activeMeta.min_events} arrivals</span>
            </button>
          </div>
          <p className="text-xs leading-relaxed text-muted-ink tabular-nums">
            Unified scale centred near the bus stop median ({busInitial.stop_median_display}, equal-weighted across
            stops). Overview reports arrival-weighted system rates ({arrivalWeightedNote}) Select any band to filter.
          </p>
        </div>

        {/* Map canvas + optional pinned stop detail drawer */}
        <div
          className={
            asTable
              ? "hidden"
              : selectedDetail
                ? "grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_310px]"
                : "grid grid-cols-1"
          }
        >
          <div
            className="relative h-[440px] w-full md:h-[min(64vh,580px)] md:min-h-[440px]"
            style={{ backgroundColor: COLORS.mapWater }}
          >
            <div
              id="map"
              ref={mapHostRef}
              role="img"
              aria-label="Map of NYC transit stops coloured by on-time arrival share over borough boundaries"
              className="relative h-full w-full overflow-hidden"
            />
            <div
              aria-live="polite"
              className="pointer-events-none absolute bottom-3 left-3 z-10 max-w-[calc(100%-68px)] rounded-md border border-rule-strong bg-surface/95 px-2.5 py-1 text-xs text-ink shadow-xs tabular-nums"
            >
              {mapError ? "Map geometry could not be loaded. Use Show as table to inspect stops." : lodStatus}
            </div>
            <div className="absolute bottom-3 right-3 z-10 flex flex-col gap-1" aria-label="Map zoom controls">
              <button
                type="button"
                onClick={() => zoomBy(ZOOM_STEP)}
                aria-label="Zoom in"
                className="flex size-9 items-center justify-center rounded-md border border-rule-strong bg-surface text-base font-bold text-ink shadow-xs hover:bg-panel"
              >
                +
              </button>
              <button
                type="button"
                onClick={() => zoomBy(1 / ZOOM_STEP)}
                aria-label="Zoom out"
                className="flex size-9 items-center justify-center rounded-md border border-rule-strong bg-surface text-base font-bold text-ink shadow-xs hover:bg-panel"
              >
                -
              </button>
            </div>
          </div>

          {selectedDetail && selectedSplit && selectedBand ? (
            <aside
              aria-label="Selected stop details"
              className="flex flex-col gap-3 border-t border-rule bg-surface p-4 lg:border-l lg:border-t-0"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <h2 className="text-base font-bold leading-snug text-ink">{selectedSplit.name}</h2>
                  <p className="num text-xs text-muted-ink">Stop ID {selectedSplit.id}</p>
                </div>
                <button
                  type="button"
                  onClick={() => setSelectedStop(null)}
                  className="rounded-md border border-rule-strong bg-surface px-2.5 py-1 text-xs font-medium text-ink hover:bg-panel"
                >
                  Close
                </button>
              </div>
              <div>
                <span
                  className="inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold text-white"
                  style={{ backgroundColor: selectedBand.color }}
                >
                  {selectedBand.label}
                </span>
              </div>
              <div className="rounded-lg bg-panel px-3 py-2.5">
                <p className="num text-2xl font-bold text-ink">
                  {selectedDetail.sufficient ? selectedDetail.display : "Not scored"}
                </p>
                <p className="mt-0.5 text-xs text-muted-ink tabular-nums">
                  {selectedDelta !== null
                    ? `${Number(selectedDelta) >= 0 ? `+${selectedDelta}` : selectedDelta} percentage points vs ${mode} stop median (${activeMeta.stop_median_display})`
                    : `Under ${activeMeta.min_events} arrivals in 2-day window`}
                </p>
              </div>
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-xs tabular-nums">
                <dt className="text-muted-ink">Arrivals (2 days)</dt>
                <dd className="text-right font-semibold text-ink">{count(selectedDetail.events)}</dd>
                <dt className="text-muted-ink">Busiest route</dt>
                <dd className="text-right font-semibold text-ink">{selectedDetail.routeId || "N/A"}</dd>
                <dt className="text-muted-ink">Direction</dt>
                <dd className="text-right font-semibold text-ink">
                  {selectedDetail.directionId === null ? "N/A" : `Direction ${selectedDetail.directionId}`}
                </dd>
                <dt className="text-muted-ink">Coordinates</dt>
                <dd className="text-right font-semibold text-ink">
                  {selectedDetail.lat.toFixed(4)}, {selectedDetail.lon.toFixed(4)}
                </dd>
              </dl>
              <button
                type="button"
                className={btnCls}
                onClick={() => {
                  const nextZ = Math.max(engineRef.current?.getZoom() ?? NYC_INITIAL_ZOOM, 10);
                  engineRef.current?.setView([selectedDetail.lon, selectedDetail.lat], nextZ, true);
                }}
              >
                Center on stop
              </button>
              <Link
                href={explorerHref(mode, selectedDetail)}
                prefetch={false}
                className="inline-flex min-h-10 items-center justify-center rounded-md bg-brand px-3 text-xs font-semibold text-white no-underline hover:bg-brand-hover"
              >
                Open hour-by-hour view
              </Link>
            </aside>
          ) : null}
        </div>

        {/* Accessible table alternative */}
        {asTable ? (
          <div className="p-4 md:p-5">
            <label className="mb-3 flex max-w-md flex-col gap-1 text-sm">
              <span className="text-xs font-semibold text-muted-ink">Filter table by stop name, ID, or route</span>
              <input
                type="search"
                value={tableQuery}
                onChange={(e) => handleTableSearch(e.target.value)}
                className="min-h-10 rounded-lg border border-rule-strong bg-surface px-3 text-sm text-ink"
                placeholder="Stop name, ID, or route"
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
                    <th scope="col" className="border-b border-rule px-3 py-2 text-left text-xs font-semibold text-muted-ink">
                      Stop
                    </th>
                    <th scope="col" className="border-b border-rule px-3 py-2 text-left text-xs font-semibold text-muted-ink">
                      Band
                    </th>
                    <th scope="col" className="border-b border-rule px-3 py-2 text-right text-xs font-semibold text-muted-ink">
                      Arrivals
                    </th>
                    <th scope="col" className="border-b border-rule px-3 py-2 text-right text-xs font-semibold text-muted-ink">
                      On time
                    </th>
                    <th scope="col" className="border-b border-rule px-3 py-2 text-right text-xs font-semibold text-muted-ink">
                      Busiest route
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {tableRows.map((stop) => {
                    const bm = bandMeta(stop.share, stop.sufficient);
                    return (
                      <tr key={stop.stopId} className="border-t border-panel hover:bg-paper/70">
                        <th scope="row" className="px-3 py-2 text-left font-medium text-ink">
                          <Link href={explorerHref(mode, stop)} prefetch={false}>
                            {stop.label}
                          </Link>
                        </th>
                        <td className="px-3 py-2 text-xs text-ink">
                          <span
                            className="mr-1.5 inline-block size-2 rounded-full"
                            style={{ backgroundColor: bm.color }}
                            aria-hidden="true"
                          />
                          {bm.label}
                        </td>
                        <td className="num px-3 py-2 text-right text-ink">{count(stop.events)}</td>
                        <td className="num px-3 py-2 text-right text-ink">
                          {stop.display}
                          {stop.sufficient ? "" : " (too few)"}
                        </td>
                        <td className="num px-3 py-2 text-right text-ink">{stop.routeId}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-xs text-muted-ink">
              Showing {tableRows.length} of {tableQuery.trim() ? "matching" : count(activeMeta.total)} stops, least
              reliable first.
            </p>
          </div>
        ) : null}

        {/* Footer: summary, NYC DCP basemap attribution + download date + SHA-256, and provenance */}
        <figcaption className="space-y-1.5 border-t border-rule bg-paper px-4 py-3 text-xs text-muted-ink md:px-5">
          <p>{activeMeta.summary}</p>
          <p>
            Basemap: NYC Department of City Planning (NYC DCP) Borough Boundaries (Clipped to Shoreline), downloaded{" "}
            <span className="num">{NYC_BOROUGHS_DATE}</span>, simplified file SHA-256{" "}
            <span className="mono-id break-all">{NYC_BOROUGHS_SHA256}</span>, together with MTA static GTFS route
            shapes. Self-hosted with zero third-party requests.
          </p>
          <ProvenanceLine source={source} />
        </figcaption>
      </figure>

      <Definitions text={activeMeta.definitions} />
    </div>
  );
}
