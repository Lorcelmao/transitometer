"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { EChart } from "@/charts/echart";
import { hcmcChoroplethOption, type HcmcMetricKey } from "@/charts/options";
import { FilterBar } from "@/components/site/filters";
import { ChartFrame, DataTable, type Column } from "@/components/story/chart-frame";
import { KpiRow, type KpiExtra } from "@/components/story/kpi-figure";
import { CheckStrip } from "@/components/story/micro-viz";
import { Caveat, Definitions } from "@/components/story/page-parts";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { fetchView } from "@/data/fetch-view";
import {
  hcmcBasemap,
  hcmcCoverage,
  type HcmcBasemap,
  type HcmcCoverage,
  type HcmcHandCheck,
  type HcmcWard,
} from "@/data/schemas";
import { count } from "@/lib/format";

const BASEMAP_URL = "/basemap/hcmc.json";
const MAP_CORE = "hcmc_wards_core";
const MAP_ALL = "hcmc_wards_all";

let basemapPromise: Promise<HcmcBasemap> | null = null;
function loadHcmcBasemap(): Promise<HcmcBasemap> {
  basemapPromise ??= Promise.all([
    fetch(BASEMAP_URL).then((res) => {
      if (!res.ok) throw new Error(`${BASEMAP_URL}: HTTP ${res.status}`);
      return res.json();
    }),
    import("@/charts/echarts-setup"),
  ])
    .then(([raw, { echarts }]) => {
      const parsed = hcmcBasemap.parse(raw);
      const coreGeo = {
        type: "FeatureCollection" as const,
        features: parsed.wards.features.filter((f) => f.properties.in_core_hcmc),
      };
      echarts.registerMap(MAP_CORE, coreGeo as unknown as Parameters<typeof echarts.registerMap>[1]);
      echarts.registerMap(
        MAP_ALL,
        parsed.wards as unknown as Parameters<typeof echarts.registerMap>[1],
      );
      return parsed;
    })
    .catch((err) => {
      basemapPromise = null;
      throw err;
    });
  return basemapPromise;
}

const METRIC_LABELS: Record<HcmcMetricKey, string> = {
  any: "Any bus stop (400 m)",
  freq_cons: "Frequent ≥ 4/h (conservative)",
  freq_mid: "Frequent ≥ 4/h (midpoint)",
};

const WARD_COLUMNS: Column<HcmcWard>[] = [
  { key: "ward_name", label: "Ward / Commune", lang: "vi", render: (w) => w.ward_name },
  { key: "area", label: "Area", numeric: true, render: (w) => w.area_display },
  { key: "any", label: "400 m (any)", numeric: true, render: (w) => w.coverage_any_display },
  {
    key: "freq_cons",
    label: "≥ 4/h (conservative)",
    numeric: true,
    render: (w) => w.coverage_freq_cons_display,
  },
  {
    key: "freq_mid",
    label: "≥ 4/h (midpoint)",
    numeric: true,
    render: (w) => w.coverage_freq_mid_display,
  },
  { key: "stops", label: "Stops", numeric: true, render: (w) => count(w.active_stops) },
  { key: "density", label: "Stops / km²", numeric: true, render: (w) => w.stops_per_km2_display },
  { key: "routes", label: "Routes", numeric: true, render: (w) => count(w.distinct_routes) },
];

const HAND_CHECK_COLUMNS: Column<HcmcHandCheck>[] = [
  { key: "ref", label: "Route", render: (r) => r.route_ref },
  { key: "corridor", label: "Corridor", lang: "vi", render: (r) => r.corridor },
  { key: "osm_km", label: "OSM km", numeric: true, render: (r) => `${r.osm_length_km.toFixed(1)} km` },
  { key: "pub_km", label: "Published km", numeric: true, render: (r) => r.published_length_km },
  { key: "osm_hw", label: "OSM interval", render: (r) => `${r.osm_headway_min} min` },
  { key: "pub_hw", label: "Published headway", render: (r) => r.published_headway_min },
  { key: "note", label: "Spot-check note", lang: "vi", render: (r) => r.assessment },
];

export function HcmcView({ initial }: { initial: HcmcCoverage }) {
  const [scope, setScope] = useState<string>(initial.scope);
  const [view, setView] = useState<HcmcCoverage>(initial);
  const [metric, setMetric] = useState<HcmcMetricKey>("any");
  const [showRoutes, setShowRoutes] = useState(true);
  const [showStops, setShowStops] = useState(false);
  const [basemap, setBasemap] = useState<HcmcBasemap | null>(null);
  const [mapError, setMapError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    loadHcmcBasemap()
      .then((bm) => {
        if (active) setBasemap(bm);
      })
      .catch((err: unknown) => {
        if (active) setMapError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      active = false;
    };
  }, []);

  const handleScopeChange = useCallback(
    (next: string) => {
      if (!next || next === scope) return;
      setScope(next);
      setLoadError(null);
      if (next === initial.scope) {
        setView(initial);
        return;
      }
      fetchView(`hcmc/${next}.json`, hcmcCoverage)
        .then(({ data }) => setView(data))
        .catch((err: unknown) => setLoadError(err instanceof Error ? err.message : String(err)));
    },
    [initial, scope],
  );

  const mapName = scope === "core_hcmc" ? MAP_CORE : MAP_ALL;
  const buildMap = useCallback(
    (font: string) =>
      hcmcChoroplethOption(
        mapName,
        view.wards,
        basemap?.routes ?? [],
        basemap?.stops ?? [],
        metric,
        METRIC_LABELS[metric],
        showRoutes,
        showStops,
        font,
      ),
    [mapName, view.wards, basemap, metric, showRoutes, showStops],
  );

  const provenanceNode = useMemo(() => {
    const p = view.provenance;
    const fetched = p.retrieved_utc ? p.retrieved_utc.slice(0, 10) : "pinned";
    return (
      <p className="text-xs text-muted-ink" data-testid="provenance">
        Source: <span className="mono-id">{p.tables.join(", ")}</span>. OSM static snapshot ({p.attribution},{" "}
        <span className="mono-id">{p.crs}</span>, fetched {fetched}); not a live service.
      </p>
    );
  }, [view.provenance]);

  const mapSummary = useMemo(() => {
    const lowest = view.bottom_wards
      .slice(0, 3)
      .map((w) => `${w.ward_name} (${w.coverage_any_display})`)
      .join(", ");
    return `${count(view.wards.length)} wards/communes in ${view.scope_label}. Lowest 400 m coverage: ${lowest || "none"}.`;
  }, [view]);

  const incompleteRoutesCount = useMemo(
    () => view.routes.filter((r) => r.osm_incomplete).length,
    [view.routes],
  );

  const kpiExtras: Record<string, KpiExtra> = useMemo(
    () => ({
      coverage_any: {
        badge: { label: "% of land area", tone: "neutral" },
      },
      coverage_freq: {
        badge: { label: "OSM interval only", tone: "attention" },
      },
      routes_mapped: {
        badge: { label: "Primary network", tone: "neutral" },
      },
      interval_coverage: {
        badge:
          view.quality_passed === view.quality_total
            ? { label: "All checks passed", tone: "pass" }
            : { label: `${view.quality_total - view.quality_passed} below target`, tone: "fail" },
        viz: <CheckStrip passed={view.quality_passed} total={view.quality_total} />,
      },
    }),
    [view.quality_passed, view.quality_total],
  );

  return (
    <div className="space-y-5">
      <FilterBar>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[13px] font-medium text-muted-ink">Scope</span>
          <ToggleGroup
            type="single"
            value={scope}
            onValueChange={handleScopeChange}
            aria-label="Geographic scope"
            className="inline-flex flex-wrap rounded-lg border border-rule bg-panel p-0.5"
            spacing={0}
          >
            {view.scopes.map((s) => (
              <ToggleGroupItem
                key={s.key}
                value={s.key}
                data-testid={`scope-${s.key}`}
                className="min-h-10 rounded-md border-0 bg-transparent px-3 text-xs font-medium text-muted-ink shadow-none data-[state=on]:bg-surface data-[state=on]:font-semibold data-[state=on]:text-ink data-[state=on]:shadow-xs sm:text-sm"
              >
                {s.short}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[13px] font-medium text-muted-ink">Layer</span>
          <ToggleGroup
            type="single"
            value={metric}
            onValueChange={(v) => v && setMetric(v as HcmcMetricKey)}
            aria-label="Coverage metric layer"
            className="inline-flex flex-wrap rounded-lg border border-rule bg-panel p-0.5"
            spacing={0}
          >
            {(Object.keys(METRIC_LABELS) as HcmcMetricKey[]).map((key) => (
              <ToggleGroupItem
                key={key}
                value={key}
                data-testid={`metric-${key}`}
                className="min-h-10 rounded-md border-0 bg-transparent px-2.5 text-xs font-medium text-muted-ink shadow-none data-[state=on]:bg-surface data-[state=on]:font-semibold data-[state=on]:text-ink data-[state=on]:shadow-xs sm:px-3"
              >
                {METRIC_LABELS[key]}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        </div>
      </FilterBar>

      {loadError ? <Caveat>Could not load scope data: {loadError}</Caveat> : null}

      <KpiRow figures={view.figures} extras={kpiExtras} />

      <Caveat>
        <strong>Scope and limitations:</strong> OpenStreetMap is community-maintained open data (
        {view.provenance.attribution}), not an official timetable or live service.{" "}
        <strong>Pre-merger HCMC (102)</strong> selects strictly the 102 commune-level units formed on pre-merger Ho Chi
        Minh City territory under Resolution <code className="mono-id text-xs">1685/NQ-UBTVQH15</code> (16 Jun 2025;{" "}
        <strong>Merged city (168)</strong> adds the 36 former <span lang="vi">Bình Dương</span> and 30 former{" "}
        <span lang="vi">Bà Rịa - Vũng Tàu</span> units). Because M1 uses natural administrative area (including{" "}
        <span lang="vi">Cần Giờ</span> mangrove forests and waterways) as its denominator, it measures{" "}
        <strong>% of land area</strong>, not <strong>% of population</strong>. M2 relies solely on OSM{" "}
        <code className="mono-id text-xs">interval</code> tags (<code className="mono-id text-xs">duration</code> is
        tagged on 0 % of routes, so there are no actual arrival times). All active HCMC bus stops are buffered before
        clipping so border-adjacent stops still contribute their 400 m walk-shed inside neighboring wards.
      </Caveat>

      <ChartFrame
        title="400 m walk-shed coverage by ward / commune"
        lead={
          <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-muted-ink">
            <span>
              Zoom or hover a ward to compare overall 400 m access against guaranteed frequent service (≥ 4 buses/h).
            </span>
            <label className="inline-flex min-h-10 cursor-pointer items-center gap-2 text-ink">
              <input
                type="checkbox"
                checked={showRoutes}
                onChange={(e) => setShowRoutes(e.target.checked)}
                className="size-4 accent-brand"
              />
              <span>Bus routes</span>
            </label>
            <label className="inline-flex min-h-10 cursor-pointer items-center gap-2 text-ink">
              <input
                type="checkbox"
                checked={showStops}
                onChange={(e) => setShowStops(e.target.checked)}
                className="size-4 accent-brand"
              />
              <span>Active stops</span>
            </label>
          </div>
        }
        summary={mapSummary}
        provenance={provenanceNode}
        chart={
          mapError ? (
            <p className="rounded-lg border border-rule bg-paper p-4 text-sm text-muted-ink">
              Could not load map geometry ({mapError}). Use &ldquo;Show as table&rdquo; to inspect every ward.
            </p>
          ) : basemap ? (
            <EChart
              build={buildMap}
              height={520}
              renderer="canvas"
              lang="vi"
              label={`Ho Chi Minh City bus coverage map (${METRIC_LABELS[metric]})`}
            />
          ) : (
            <div className="flex h-[520px] items-center justify-center rounded-lg border border-rule bg-paper text-sm text-muted-ink">
              Loading ward boundaries and bus corridors...
            </div>
          )
        }
        table={
          <DataTable
            rows={view.wards}
            columns={WARD_COLUMNS}
            caption={`Ward-level 400 m bus coverage in ${view.scope_label}`}
            rowKey={(w) => w.ward_id}
          />
        }
      />

      <section
        className="rounded-xl border border-rule bg-surface p-4 shadow-xs md:p-5"
        aria-labelledby="hcmc-gaps"
      >
        <h2 id="hcmc-gaps" className="text-[17px] font-semibold text-ink">
          Priority gaps for network planners (U7)
        </h2>
        <p className="mt-1 max-w-prose text-xs text-muted-ink">
          Lowest-covered wards and communes in <strong>{view.scope_label}</strong>, ordered by 400 m walk-shed share
          (largest land area first on ties).
        </p>
        <div className="mt-4">
          <DataTable
            rows={view.bottom_wards}
            columns={WARD_COLUMNS}
            caption="15 lowest-covered wards and communes"
            rowKey={(w) => `low-${w.ward_id}`}
          />
        </div>
      </section>

      <section
        className="rounded-xl border border-rule bg-surface p-4 shadow-xs md:p-5"
        aria-labelledby="hcmc-quality"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="hcmc-quality" className="text-[17px] font-semibold text-ink">
            OpenStreetMap completeness audit (BR7 counterpart)
          </h2>
          <span className="num rounded-full bg-panel px-2.5 py-0.5 text-xs font-semibold text-ink">
            {view.quality_passed} of {view.quality_total} passed
          </span>
        </div>
        <p className="mt-1 max-w-prose text-xs text-muted-ink">
          Checked on{" "}
          <span lang="vi" className="font-semibold text-ink">
            {view.provenance.primary_network}
          </span>
          . Missing <code className="mono-id">duration</code> tags explain why derived GTFS keeps stop order and
          headways without synthetic arrival times.
        </p>
        <div className="mt-4">
          <DataTable
            rows={view.quality}
            columns={[
              { key: "label", label: "Check", render: (q) => q.label },
              { key: "val", label: "Measured", numeric: true, render: (q) => q.value_display },
              { key: "ratio", label: "Count", numeric: true, render: (q) => q.ratio_display },
              { key: "target", label: "Target", numeric: true, render: (q) => q.threshold_display },
              {
                key: "status",
                label: "Status",
                render: (q) => (
                  <span
                    className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                      q.passed ? "bg-pass-soft text-pass-text" : "bg-fail-soft text-fail-text"
                    }`}
                  >
                    {q.result}
                  </span>
                ),
              },
            ]}
            caption="OpenStreetMap completeness checks for HCMC bus routes"
            rowKey={(q) => q.metric}
          />
        </div>
      </section>

      {view.routes.length > 0 ? (
        <section
          className="rounded-xl border border-rule bg-surface p-4 shadow-xs md:p-5"
          aria-labelledby="hcmc-routes"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 id="hcmc-routes" className="text-[17px] font-semibold text-ink">
              Mapped HCMC bus routes (OSM-derived)
            </h2>
            {incompleteRoutesCount > 0 ? (
              <span className="rounded-full bg-attention-soft px-2.5 py-0.5 text-xs font-semibold text-attention-text">
                {incompleteRoutesCount} flagged incomplete OSM
              </span>
            ) : null}
          </div>
          <p className="mt-1 max-w-prose text-xs text-muted-ink">
            {count(view.routes.length)} distinct routes in{" "}
            <span lang="vi" className="font-semibold text-ink">
              {view.provenance.primary_network}
            </span>
            . {count(incompleteRoutesCount)} route(s) are marked{" "}
            <strong className="text-ink">Incomplete OSM data</strong> instead of displaying unreliable OSM way sums
            (endpoint-only stop mapping or unverified corridor detours above 120 km); stop-based walk-shed coverage is
            unaffected.
          </p>
          <div className="mt-4">
            <DataTable
              rows={view.routes}
              columns={[
                { key: "ref", label: "Route", render: (r) => r.route_ref },
                { key: "name", label: "Corridor", lang: "vi", render: (r) => r.route_name },
                { key: "dirs", label: "Dirs", numeric: true, render: (r) => count(r.directions) },
                {
                  key: "stops",
                  label: "Mapped stops / dir",
                  numeric: true,
                  render: (r) => r.avg_stops_per_dir.toFixed(1),
                },
                {
                  key: "length",
                  label: "Length",
                  numeric: true,
                  render: (r) =>
                    r.osm_incomplete ? (
                      <span className="inline-flex rounded-full bg-attention-soft px-2.5 py-0.5 text-xs font-semibold text-attention-text">
                        {r.length_display}
                      </span>
                    ) : (
                      r.length_display
                    ),
                },
                { key: "interval", label: "OSM interval", render: (r) => r.sample_interval ?? "—" },
                { key: "note", label: "OSM data note", render: (r) => r.osm_note || "—" },
              ]}
              caption="Mapped HCMC bus routes from OpenStreetMap"
              rowKey={(r) => `route-${r.route_ref}`}
            />
          </div>
        </section>
      ) : null}

      {view.hand_checks.length > 0 ? (
        <section
          className="rounded-xl border border-rule bg-surface p-4 shadow-xs md:p-5"
          aria-labelledby="hcmc-hand-checks"
        >
          <h2 id="hcmc-hand-checks" className="text-[17px] font-semibold text-ink">
            Spot-check against published HCMC routes
          </h2>
          <p className="mt-1 max-w-prose text-xs text-muted-ink">
            Five familiar Ho Chi Minh City corridors (including HCMUT campus routes 08, 19 and 50) compared against
            published operator disclosures to quantify OSM accuracy and drift.
          </p>
          <div className="mt-4">
            <DataTable
              rows={view.hand_checks}
              columns={HAND_CHECK_COLUMNS}
              caption="Spot-check of 5 HCMC bus routes: OSM vs published disclosures"
              rowKey={(r) => `hc-${r.route_ref}`}
            />
          </div>
        </section>
      ) : null}

      <Definitions text={view.definitions} lang="vi" />
    </div>
  );
}
