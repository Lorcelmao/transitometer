/**
 * Dedicated Canvas 2D renderer for the NYC Stop map (/diagnostics/map/).
 *
 * Replaces ECharts on the stop map route to eliminate ~220 KB gzip of shared chart runtime and
 * synchronous >200 ms script/scene-graph tasks on throttled mobile CPUs, while preserving exact
 * NYC DCP borough geometry, WCAG AA diverging bands, 670 m grid to stop zoom LOD, crisp white
 * dot halos, cursor-anchored wheel/pinch zoom, drag pan, hover ring and HTML tooltips.
 */
import {
  bandIndex,
  BOROUGH_LABELS,
  gridCellSize,
  LOD_ZOOM_THRESHOLD,
  MAP_DIVERGING_BANDS,
  MAP_ZOOM_LIMIT,
  NYC_CENTER,
  NYC_INITIAL_ZOOM,
  stopDotSize,
  STREETS_FROM_ZOOM,
  type BandFilter,
  type Bbox,
  type MapGridCell,
  type MapLayers,
  type MapStop,
  type StreetPolyline,
  type SubwayLineGroup,
} from "@/charts/options";
import { COLORS } from "@/charts/theme";

const TWO_PI = Math.PI * 2;
export const NYC_COS_LAT = Math.cos((40.71 * Math.PI) / 180);
const WHEEL_ZOOM_SENSITIVITY = 0.00072;
const DEFAULT_BOUNDS: Bbox = [-74.2556, -73.7, 40.4961, 40.9156];

export type GeoJsonCollection = {
  type?: string;
  features?: {
    geometry?: {
      type?: string;
      coordinates?: unknown;
    };
  }[];
};

export type MapViewport = {
  width: number;
  height: number;
  centerLon: number;
  centerLat: number;
  zoom: number;
  baseScale: number;
};

export type HitTarget = {
  kind: "grid" | "stop";
  index: number;
  lon: number;
  lat: number;
  px: number;
  py: number;
  radius: number;
  priority: number;
};

export type CanvasRenderState = {
  mode: "bus" | "subway";
  useGrid: boolean;
  gridCells: readonly MapGridCell[];
  stops: readonly MapStop[];
  filterBand: BandFilter;
  layers: MapLayers;
  streets: readonly StreetPolyline[] | null;
  selectedStop: { lon: number; lat: number } | null;
  font: string;
};

export type StopMapCallbacks = {
  onViewChange: (zoom: number) => void;
  onVisibleCount: (visibleCount: number, useGrid: boolean, zoom: number) => void;
  onClickGrid: (index: number, cell: MapGridCell) => void;
  onClickStop: (index: number, stop: MapStop) => void;
  formatGridTooltip: (index: number) => string;
  formatStopTooltip: (index: number) => string;
};

/** Extract [minLon, maxLon, minLat, maxLat] from a GeoJSON FeatureCollection. */
export function computeGeoBounds(geojson: GeoJsonCollection): Bbox {
  let minLon = Infinity;
  let maxLon = -Infinity;
  let minLat = Infinity;
  let maxLat = -Infinity;

  const visitRing = (ring: unknown) => {
    if (!Array.isArray(ring)) return;
    for (let i = 0; i < ring.length; i++) {
      const pt = ring[i];
      if (Array.isArray(pt) && typeof pt[0] === "number" && typeof pt[1] === "number") {
        if (pt[0] < minLon) minLon = pt[0];
        if (pt[0] > maxLon) maxLon = pt[0];
        if (pt[1] < minLat) minLat = pt[1];
        if (pt[1] > maxLat) maxLat = pt[1];
      }
    }
  };

  for (const feat of geojson.features ?? []) {
    const g = feat.geometry;
    if (!g) continue;
    if (g.type === "Polygon" && Array.isArray(g.coordinates)) {
      for (const ring of g.coordinates) visitRing(ring);
    } else if (g.type === "MultiPolygon" && Array.isArray(g.coordinates)) {
      for (const poly of g.coordinates) {
        if (Array.isArray(poly)) {
          for (const ring of poly) visitRing(ring);
        }
      }
    }
  }

  if (!Number.isFinite(minLon) || maxLon <= minLon || maxLat <= minLat) {
    return DEFAULT_BOUNDS;
  }
  return [minLon, maxLon, minLat, maxLat];
}

export function computeBaseScale(width: number, height: number, bounds: Bbox): number {
  const pad = Math.min(width, height) * 0.04;
  const availW = Math.max(1, width - pad * 2);
  const availH = Math.max(1, height - pad * 2);
  const geoW = Math.max(1e-5, (bounds[1] - bounds[0]) * NYC_COS_LAT);
  const geoH = Math.max(1e-5, bounds[3] - bounds[2]);
  return Math.min(availW / geoW, availH / geoH);
}

export function lonLatToPixel(lon: number, lat: number, vp: MapViewport): [number, number] {
  const scale = vp.baseScale * vp.zoom;
  return [
    vp.width * 0.5 + (lon - vp.centerLon) * NYC_COS_LAT * scale,
    vp.height * 0.5 - (lat - vp.centerLat) * scale,
  ];
}

export function pixelToLonLat(px: number, py: number, vp: MapViewport): [number, number] {
  const scale = vp.baseScale * vp.zoom;
  return [
    vp.centerLon + (px - vp.width * 0.5) / (NYC_COS_LAT * scale),
    vp.centerLat - (py - vp.height * 0.5) / scale,
  ];
}

export function viewportToBbox(vp: MapViewport, marginRatio: number): Bbox {
  const [minLon, maxLat] = pixelToLonLat(0, 0, vp);
  const [maxLon, minLat] = pixelToLonLat(vp.width, vp.height, vp);
  const dLon = (maxLon - minLon) * marginRatio;
  const dLat = (maxLat - minLat) * marginRatio;
  return [minLon - dLon, maxLon + dLon, minLat - dLat, maxLat + dLat];
}

/** Nearest visible marker within hit tolerance; higher priority (redder band) breaks near ties. */
export function findHitTarget(targets: readonly HitTarget[], x: number, y: number): HitTarget | null {
  let best: HitTarget | null = null;
  let bestScore = Infinity;
  for (let i = 0; i < targets.length; i++) {
    const t = targets[i];
    const maxR = Math.max(11, t.radius + 5);
    const dx = x - t.px;
    if (dx > maxR || dx < -maxR) continue;
    const dy = y - t.py;
    if (dy > maxR || dy < -maxR) continue;
    const d2 = dx * dx + dy * dy;
    if (d2 > maxR * maxR) continue;
    const score = Math.sqrt(d2) - t.priority * 0.35;
    if (score < bestScore) {
      bestScore = score;
      best = t;
    }
  }
  return best;
}

function buildBoroughPath(geojson: GeoJsonCollection, refLon: number, refLat: number): Path2D {
  const path = new Path2D();
  const addRing = (ring: unknown) => {
    if (!Array.isArray(ring) || ring.length < 3) return;
    let started = false;
    for (let i = 0; i < ring.length; i++) {
      const pt = ring[i];
      if (!Array.isArray(pt) || typeof pt[0] !== "number" || typeof pt[1] !== "number") continue;
      const mx = (pt[0] - refLon) * NYC_COS_LAT;
      const my = -(pt[1] - refLat);
      if (!started) {
        path.moveTo(mx, my);
        started = true;
      } else {
        path.lineTo(mx, my);
      }
    }
    if (started) path.closePath();
  };

  for (const feat of geojson.features ?? []) {
    const g = feat.geometry;
    if (!g) continue;
    if (g.type === "Polygon" && Array.isArray(g.coordinates)) {
      for (const ring of g.coordinates) addRing(ring);
    } else if (g.type === "MultiPolygon" && Array.isArray(g.coordinates)) {
      for (const poly of g.coordinates) {
        if (Array.isArray(poly)) {
          for (const ring of poly) addRing(ring);
        }
      }
    }
  }
  return path;
}

function buildSubwayPaths(
  groups: readonly SubwayLineGroup[],
  refLon: number,
  refLat: number,
): { merged: Path2D; colored: { color: string; path: Path2D }[] } {
  const merged = new Path2D();
  const colored: { color: string; path: Path2D }[] = [];
  for (let g = 0; g < groups.length; g++) {
    const grp = groups[g];
    const p = new Path2D();
    for (let l = 0; l < grp.lines.length; l++) {
      const coords = grp.lines[l];
      if (coords.length < 2) continue;
      for (let i = 0; i < coords.length; i++) {
        const mx = (coords[i][0] - refLon) * NYC_COS_LAT;
        const my = -(coords[i][1] - refLat);
        if (i === 0) {
          merged.moveTo(mx, my);
          p.moveTo(mx, my);
        } else {
          merged.lineTo(mx, my);
          p.lineTo(mx, my);
        }
      }
    }
    colored.push({ color: grp.color, path: p });
  }
  return { merged, colored };
}

function appendRoundedRect(ctx: CanvasRenderingContext2D, x: number, y: number, size: number, r: number): void {
  const x2 = x + size;
  const y2 = y + size;
  ctx.moveTo(x + r, y);
  ctx.lineTo(x2 - r, y);
  ctx.quadraticCurveTo(x2, y, x2, y + r);
  ctx.lineTo(x2, y2 - r);
  ctx.quadraticCurveTo(x2, y2, x2 - r, y2);
  ctx.lineTo(x + r, y2);
  ctx.quadraticCurveTo(x, y2, x, y2 - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}

export class StopMapCanvas {
  private host: HTMLElement;
  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private hoverRing: HTMLDivElement;
  private tooltipEl: HTMLDivElement;
  private callbacks: StopMapCallbacks;

  private bounds: Bbox = DEFAULT_BOUNDS;
  private refLon: number = NYC_CENTER[0];
  private refLat: number = NYC_CENTER[1];
  private boroughPath: Path2D | null = null;
  private subwayPaths: { merged: Path2D; colored: { color: string; path: Path2D }[] } | null = null;

  private width = 0;
  private height = 0;
  private dpr = 1;
  private baseScale = 1;
  private centerLon: number = NYC_CENTER[0];
  private centerLat: number = NYC_CENTER[1];
  private zoom: number = NYC_INITIAL_ZOOM;

  private state: CanvasRenderState = {
    mode: "bus",
    useGrid: true,
    gridCells: [],
    stops: [],
    filterBand: null,
    layers: { streets: true, subway: true, lineColors: false },
    streets: null,
    selectedStop: null,
    font: "sans-serif",
  };

  private hitTargets: HitTarget[] = [];
  private hovered: HitTarget | null = null;
  private rafId: number | null = null;
  private resizeObserver: ResizeObserver;
  private disposed = false;

  // Pointer pan & 2-finger pinch tracking
  private activePointers = new Map<number, { x: number; y: number }>();
  private dragStart: { x: number; y: number; lon: number; lat: number; moved: boolean } | null = null;
  private pinchPrev: { dist: number; midX: number; midY: number } | null = null;

  constructor(host: HTMLElement, callbacks: StopMapCallbacks) {
    this.host = host;
    this.callbacks = callbacks;

    this.canvas = document.createElement("canvas");
    this.canvas.style.width = "100%";
    this.canvas.style.height = "100%";
    this.canvas.style.display = "block";
    this.canvas.style.touchAction = "none";
    this.canvas.style.cursor = "grab";
    host.appendChild(this.canvas);

    const ctx = this.canvas.getContext("2d", { alpha: false });
    if (!ctx) throw new Error("2D canvas context unavailable");
    this.ctx = ctx;

    this.hoverRing = document.createElement("div");
    this.hoverRing.setAttribute("aria-hidden", "true");
    this.hoverRing.style.cssText =
      "position:absolute;left:0;top:0;width:16px;height:16px;margin:-8px 0 0 -8px;" +
      "border-radius:9999px;border:2.5px solid #0f172a;pointer-events:none;z-index:10;" +
      "opacity:0;box-shadow:0 0 0 2px rgba(255,255,255,0.92);will-change:transform;";
    host.appendChild(this.hoverRing);

    this.tooltipEl = document.createElement("div");
    this.tooltipEl.className = "map-tooltip";
    this.tooltipEl.style.cssText =
      "position:absolute;left:0;top:0;z-index:20;pointer-events:none;opacity:0;display:none;" +
      "background:#ffffff;color:#0f172a;border:1px solid #64748b;border-radius:10px;" +
      "padding:10px 12px;max-width:min(285px,calc(100% - 20px));white-space:normal;" +
      "box-shadow:0 10px 24px rgba(15,23,42,0.18);";
    host.appendChild(this.tooltipEl);

    this.bindEvents();
    this.measure();
    this.resizeObserver = new ResizeObserver(() => {
      if (!this.disposed) this.resize();
    });
    this.resizeObserver.observe(host);
  }

  setBoroughs(geojson: GeoJsonCollection): void {
    this.bounds = computeGeoBounds(geojson);
    this.refLon = (this.bounds[0] + this.bounds[1]) * 0.5;
    this.refLat = (this.bounds[2] + this.bounds[3]) * 0.5;
    this.centerLon = this.refLon;
    this.centerLat = this.refLat;
    this.boroughPath = buildBoroughPath(geojson, this.refLon, this.refLat);
    this.baseScale = computeBaseScale(this.width, this.height, this.bounds);
    this.scheduleDraw();
  }

  setSubwayLines(groups: readonly SubwayLineGroup[]): void {
    this.subwayPaths = buildSubwayPaths(groups, this.refLon, this.refLat);
    this.scheduleDraw();
  }

  setState(next: CanvasRenderState): void {
    this.state = next;
    this.hideTooltip();
    this.scheduleDraw();
  }

  getZoom(): number {
    return this.zoom;
  }

  getViewport(): MapViewport {
    return {
      width: this.width,
      height: this.height,
      centerLon: this.centerLon,
      centerLat: this.centerLat,
      zoom: this.zoom,
      baseScale: this.baseScale,
    };
  }

  getViewportBbox(marginRatio: number): Bbox | null {
    if (this.width < 10 || this.height < 10 || this.baseScale <= 0) return null;
    return viewportToBbox(this.getViewport(), marginRatio);
  }

  setView(center: readonly [number, number] | null, zoom: number, notify = true): void {
    this.zoom = Math.min(MAP_ZOOM_LIMIT.max, Math.max(MAP_ZOOM_LIMIT.min, zoom));
    if (center) {
      this.centerLon = center[0];
      this.centerLat = center[1];
    }
    this.clampCenter();
    this.hideTooltip();
    this.scheduleDraw();
    if (notify) this.callbacks.onViewChange(this.zoom);
  }

  resetView(): void {
    this.zoom = NYC_INITIAL_ZOOM;
    this.centerLon = this.refLon;
    this.centerLat = this.refLat;
    this.hideTooltip();
    this.scheduleDraw();
  }

  resize(): void {
    this.measure();
    this.scheduleDraw();
  }

  dispose(): void {
    this.disposed = true;
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId);
      this.rafId = null;
    }
    this.resizeObserver.disconnect();
    this.unbindEvents();
    this.canvas.remove();
    this.hoverRing.remove();
    this.tooltipEl.remove();
  }

  private measure(): void {
    const rect = this.host.getBoundingClientRect();
    const w = Math.max(0, Math.round(rect.width));
    const h = Math.max(0, Math.round(rect.height));
    if (w < 10 || h < 10) return;
    this.dpr = Math.min(window.devicePixelRatio || 1, 2);
    if (w !== this.width || h !== this.height) {
      this.width = w;
      this.height = h;
      this.canvas.width = Math.round(w * this.dpr);
      this.canvas.height = Math.round(h * this.dpr);
    }
    this.baseScale = computeBaseScale(this.width, this.height, this.bounds);
  }

  private clampCenter(): void {
    const marginLon = 0.25;
    const marginLat = 0.2;
    this.centerLon = Math.min(this.bounds[1] + marginLon, Math.max(this.bounds[0] - marginLon, this.centerLon));
    this.centerLat = Math.min(this.bounds[3] + marginLat, Math.max(this.bounds[2] - marginLat, this.centerLat));
  }

  private scheduleDraw(): void {
    if (this.disposed || this.rafId !== null) return;
    this.rafId = requestAnimationFrame(() => {
      this.rafId = null;
      if (!this.disposed) this.draw();
    });
  }

  private draw(): void {
    if (this.width < 10 || this.height < 10 || this.baseScale <= 0) return;
    const ctx = this.ctx;
    const w = this.width;
    const h = this.height;
    const vp = this.getViewport();
    const scale = vp.baseScale * vp.zoom;
    const compact = window.innerWidth <= 768;
    const { mode, filterBand, layers, streets, selectedStop, font } = this.state;
    const useGrid =
      mode === "bus" &&
      (vp.zoom < LOD_ZOOM_THRESHOLD || (this.state.stops.length === 0 && this.state.gridCells.length > 0));

    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);

    // 1. Ocean background
    ctx.fillStyle = COLORS.mapWater;
    ctx.fillRect(0, 0, w, h);

    // 2. Five NYC boroughs (pre-projected Path2D)
    const tx = w * 0.5 - (this.centerLon - this.refLon) * NYC_COS_LAT * scale;
    const ty = h * 0.5 + (this.centerLat - this.refLat) * scale;
    if (this.boroughPath) {
      ctx.save();
      ctx.translate(tx, ty);
      ctx.scale(scale, scale);
      ctx.fillStyle = COLORS.mapLand;
      ctx.fill(this.boroughPath);
      ctx.strokeStyle = COLORS.mapShoreline;
      ctx.lineWidth = 1 / scale;
      ctx.lineJoin = "round";
      ctx.stroke(this.boroughPath);
      ctx.restore();
    }

    const viewBbox = viewportToBbox(vp, 0.04);

    // 3. Merged bus street network (bus mode only, zoomed into corridors)
    const streetZoomMin = compact ? 3.2 : STREETS_FROM_ZOOM;
    if (mode === "bus" && layers.streets && streets && vp.zoom >= streetZoomMin) {
      ctx.save();
      ctx.beginPath();
      for (let i = 0; i < streets.length; i++) {
        const s = streets[i];
        if (s.maxLon < viewBbox[0] || s.minLon > viewBbox[1] || s.maxLat < viewBbox[2] || s.minLat > viewBbox[3]) {
          continue;
        }
        const coords = s.coords;
        for (let j = 0; j < coords.length; j++) {
          const px = w * 0.5 + (coords[j][0] - this.centerLon) * NYC_COS_LAT * scale;
          const py = h * 0.5 - (coords[j][1] - this.centerLat) * scale;
          if (j === 0) ctx.moveTo(px, py);
          else ctx.lineTo(px, py);
        }
      }
      ctx.strokeStyle = COLORS.mapStreets;
      ctx.globalAlpha = 0.82;
      ctx.lineWidth = vp.zoom >= 5 ? 1.15 : 0.85;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.stroke();
      ctx.restore();
    }

    // 4. Subway line network (pre-projected Path2D)
    if (layers.subway && this.subwayPaths && (mode === "subway" || vp.zoom >= STREETS_FROM_ZOOM)) {
      ctx.save();
      ctx.translate(tx, ty);
      ctx.scale(scale, scale);
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      if (layers.lineColors) {
        ctx.globalAlpha = 0.85;
        ctx.lineWidth = (vp.zoom >= 4 ? 2.0 : 1.65) / scale;
        for (let i = 0; i < this.subwayPaths.colored.length; i++) {
          const g = this.subwayPaths.colored[i];
          ctx.strokeStyle = g.color;
          ctx.stroke(g.path);
        }
      } else {
        ctx.globalAlpha = 0.82;
        ctx.strokeStyle = COLORS.mapSubway;
        ctx.lineWidth = (vp.zoom >= 4 ? 1.7 : 1.35) / scale;
        ctx.stroke(this.subwayPaths.merged);
      }
      ctx.restore();
    }

    // 5. Marks: either 670 m neighborhood grid OR viewport-culled individual stops
    const targets: HitTarget[] = [];
    let visibleCount = 0;

    if (useGrid) {
      const cells = this.state.gridCells;
      const size = gridCellSize(vp.zoom, compact);
      const half = size * 0.5;
      const cornerR = Math.min(2, size * 0.28);
      const buckets: { px: number; py: number }[][] = [[], [], [], [], []];
      const thinPts: { px: number; py: number }[] = [];

      for (let i = 0; i < cells.length; i++) {
        const c = cells[i];
        const lon = c[0];
        const lat = c[1];
        if (lon < viewBbox[0] || lon > viewBbox[1] || lat < viewBbox[2] || lat > viewBbox[3]) continue;
        const share = c[3];
        const suff = c[5] > 0 && share !== null;
        const bi = suff ? bandIndex(share) : -1;
        if (filterBand !== null) {
          if (filterBand === "thin" && bi !== -1) continue;
          if (filterBand !== "thin" && bi !== filterBand) continue;
        }
        const px = w * 0.5 + (lon - this.centerLon) * NYC_COS_LAT * scale;
        const py = h * 0.5 - (lat - this.centerLat) * scale;
        visibleCount++;
        if (bi === -1) {
          thinPts.push({ px, py });
          targets.push({ kind: "grid", index: i, lon, lat, px, py, radius: half + 1, priority: 0 });
        } else {
          buckets[bi].push({ px, py });
          targets.push({ kind: "grid", index: i, lon, lat, px, py, radius: half + 1, priority: 5 - bi });
        }
      }

      if (thinPts.length) {
        ctx.beginPath();
        for (let i = 0; i < thinPts.length; i++) {
          appendRoundedRect(ctx, thinPts[i].px - half, thinPts[i].py - half, size, cornerR);
        }
        ctx.fillStyle = "#ffffff";
        ctx.fill();
        ctx.strokeStyle = COLORS.mapThinStroke;
        ctx.lineWidth = 1.25;
        ctx.stroke();
      }

      // Draw Reliable (4) first and Critical (0) last so critical corridors always stay on top
      for (let b = 4; b >= 0; b--) {
        const pts = buckets[b];
        if (!pts.length) continue;
        ctx.beginPath();
        for (let i = 0; i < pts.length; i++) {
          appendRoundedRect(ctx, pts[i].px - half, pts[i].py - half, size, cornerR);
        }
        ctx.fillStyle = MAP_DIVERGING_BANDS[b].color;
        ctx.fill();
        ctx.strokeStyle = "rgba(255,255,255,0.92)";
        ctx.lineWidth = 0.65;
        ctx.stroke();
      }
    } else {
      const stops = this.state.stops;
      const dotR = stopDotSize(vp.zoom, mode, compact) * 0.5;
      const strokeW = dotR >= 4 ? 1.2 : dotR >= 2.8 ? 0.9 : 0.65;
      const buckets: { px: number; py: number }[][] = [[], [], [], [], []];
      const thinPts: { px: number; py: number }[] = [];

      for (let i = 0; i < stops.length; i++) {
        const s = stops[i];
        if (s.lon < viewBbox[0] || s.lon > viewBbox[1] || s.lat < viewBbox[2] || s.lat > viewBbox[3]) continue;
        const bi = s.sufficient ? bandIndex(s.share) : -1;
        if (filterBand !== null) {
          if (filterBand === "thin" && bi !== -1) continue;
          if (filterBand !== "thin" && bi !== filterBand) continue;
        }
        const px = w * 0.5 + (s.lon - this.centerLon) * NYC_COS_LAT * scale;
        const py = h * 0.5 - (s.lat - this.centerLat) * scale;
        visibleCount++;
        if (bi === -1) {
          thinPts.push({ px, py });
          targets.push({ kind: "stop", index: i, lon: s.lon, lat: s.lat, px, py, radius: dotR, priority: 0 });
        } else {
          buckets[bi].push({ px, py });
          targets.push({ kind: "stop", index: i, lon: s.lon, lat: s.lat, px, py, radius: dotR, priority: 5 - bi });
        }
      }

      if (thinPts.length) {
        const thinR = Math.max(2.6, dotR * 0.92);
        ctx.beginPath();
        for (let i = 0; i < thinPts.length; i++) {
          ctx.moveTo(thinPts[i].px + thinR, thinPts[i].py);
          ctx.arc(thinPts[i].px, thinPts[i].py, thinR, 0, TWO_PI);
        }
        ctx.fillStyle = "#ffffff";
        ctx.fill();
        ctx.strokeStyle = COLORS.mapThinStroke;
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }

      for (let b = 4; b >= 0; b--) {
        const pts = buckets[b];
        if (!pts.length) continue;
        ctx.beginPath();
        for (let i = 0; i < pts.length; i++) {
          ctx.moveTo(pts[i].px + dotR, pts[i].py);
          ctx.arc(pts[i].px, pts[i].py, dotR, 0, TWO_PI);
        }
        ctx.fillStyle = MAP_DIVERGING_BANDS[b].color;
        ctx.fill();
        ctx.strokeStyle = "rgba(255,255,255,0.92)";
        ctx.lineWidth = strokeW;
        ctx.stroke();
      }
    }

    // 6. Selected stop highlight ring
    if (selectedStop) {
      const [sx, sy] = lonLatToPixel(selectedStop.lon, selectedStop.lat, vp);
      const ringR = Math.max(7.5, stopDotSize(vp.zoom, mode, compact) * 0.5 + 3.5);
      ctx.save();
      ctx.beginPath();
      ctx.arc(sx, sy, ringR, 0, TWO_PI);
      ctx.strokeStyle = "rgba(255,255,255,0.95)";
      ctx.lineWidth = 5;
      ctx.stroke();
      ctx.strokeStyle = COLORS.ink;
      ctx.lineWidth = 2.5;
      ctx.stroke();
      ctx.restore();
    }

    // 7. Borough labels at city overview zoom
    if (vp.zoom < 2.6) {
      ctx.save();
      ctx.font = `700 11.5px ${font}`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.lineJoin = "round";
      ctx.lineWidth = 3.5;
      ctx.strokeStyle = "rgba(255,255,255,0.92)";
      ctx.fillStyle = "#1e293b";
      for (let i = 0; i < BOROUGH_LABELS.length; i++) {
        const b = BOROUGH_LABELS[i];
        const [bx, by] = lonLatToPixel(b.value[0], b.value[1], vp);
        ctx.strokeText(b.name, bx, by);
        ctx.fillText(b.name, bx, by);
      }
      ctx.restore();
    }

    this.hitTargets = targets;
    this.callbacks.onVisibleCount(visibleCount, useGrid, vp.zoom);
  }

  private showTooltip(target: HitTarget): void {
    this.hovered = target;
    this.hoverRing.style.transform = `translate3d(${target.px.toFixed(1)}px, ${target.py.toFixed(1)}px, 0)`;
    this.hoverRing.style.opacity = "1";

    const html =
      target.kind === "grid"
        ? this.callbacks.formatGridTooltip(target.index)
        : this.callbacks.formatStopTooltip(target.index);
    if (!html) {
      this.hideTooltip();
      return;
    }

    this.tooltipEl.innerHTML = html;
    this.tooltipEl.style.display = "block";
    this.tooltipEl.style.opacity = "1";

    const tipW = this.tooltipEl.offsetWidth || 250;
    const tipH = this.tooltipEl.offsetHeight || 130;
    const pad = 10;
    const offset = 14;
    let left: number;
    let top: number;
    if (this.width < tipW + 90) {
      // Narrow screens: keep the hovered dot and ring visible above or below the tooltip card.
      left = Math.max(pad, Math.min(this.width - tipW - pad, target.px - tipW * 0.5));
      top = target.py + offset + 4;
      if (top + tipH > this.height - pad) {
        top = Math.max(pad, target.py - tipH - offset - 4);
      }
    } else {
      left = target.px + offset;
      if (left + tipW > this.width - pad) {
        left = Math.max(pad, target.px - tipW - offset);
      }
      top = target.py - tipH * 0.4;
      if (top + tipH > this.height - pad) {
        top = Math.max(pad, this.height - tipH - pad);
      }
      if (top < pad) top = pad;
    }
    this.tooltipEl.style.transform = `translate3d(${left.toFixed(1)}px, ${top.toFixed(1)}px, 0)`;
  }

  private hideTooltip(): void {
    if (!this.hovered && this.tooltipEl.style.display === "none") return;
    this.hovered = null;
    this.hoverRing.style.opacity = "0";
    this.tooltipEl.style.opacity = "0";
    this.tooltipEl.style.display = "none";
  }

  private onWheel = (e: WheelEvent): void => {
    e.preventDefault();
    if (this.width < 10 || this.height < 10) return;
    const rect = this.canvas.getBoundingClientRect();
    const ox = e.clientX - rect.left;
    const oy = e.clientY - rect.top;
    const clampedDelta = Math.max(-420, Math.min(420, e.deltaY));
    const factor = Math.exp(-clampedDelta * WHEEL_ZOOM_SENSITIVITY);
    const nextZoom = Math.min(MAP_ZOOM_LIMIT.max, Math.max(MAP_ZOOM_LIMIT.min, this.zoom * factor));
    if (Math.abs(nextZoom - this.zoom) < 1e-4) return;

    const vp = this.getViewport();
    const [geoLon, geoLat] = pixelToLonLat(ox, oy, vp);
    this.zoom = nextZoom;
    const nextScale = this.baseScale * this.zoom;
    this.centerLon = geoLon - (ox - this.width * 0.5) / (NYC_COS_LAT * nextScale);
    this.centerLat = geoLat + (oy - this.height * 0.5) / nextScale;
    this.clampCenter();
    this.hideTooltip();
    this.scheduleDraw();
    this.callbacks.onViewChange(this.zoom);
  };

  private onPointerDown = (e: PointerEvent): void => {
    if (e.button !== 0 && e.pointerType === "mouse") return;
    const rect = this.canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    this.canvas.setPointerCapture(e.pointerId);
    this.activePointers.set(e.pointerId, { x, y });

    if (this.activePointers.size === 1) {
      this.dragStart = { x, y, lon: this.centerLon, lat: this.centerLat, moved: false };
      this.pinchPrev = null;
      this.canvas.style.cursor = "grabbing";
    } else if (this.activePointers.size === 2) {
      const pts = [...this.activePointers.values()];
      this.dragStart = null;
      this.pinchPrev = {
        dist: Math.max(1, Math.hypot(pts[1].x - pts[0].x, pts[1].y - pts[0].y)),
        midX: (pts[0].x + pts[1].x) * 0.5,
        midY: (pts[0].y + pts[1].y) * 0.5,
      };
    }
  };

  private onPointerMove = (e: PointerEvent): void => {
    const rect = this.canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    if (this.activePointers.has(e.pointerId)) {
      this.activePointers.set(e.pointerId, { x, y });
      if (this.activePointers.size === 2 && this.pinchPrev) {
        const pts = [...this.activePointers.values()];
        const dist = Math.max(1, Math.hypot(pts[1].x - pts[0].x, pts[1].y - pts[0].y));
        const midX = (pts[0].x + pts[1].x) * 0.5;
        const midY = (pts[0].y + pts[1].y) * 0.5;
        const ratio = dist / this.pinchPrev.dist;
        const vp = this.getViewport();
        const [geoLon, geoLat] = pixelToLonLat(this.pinchPrev.midX, this.pinchPrev.midY, vp);
        this.zoom = Math.min(MAP_ZOOM_LIMIT.max, Math.max(MAP_ZOOM_LIMIT.min, this.zoom * ratio));
        const nextScale = this.baseScale * this.zoom;
        this.centerLon = geoLon - (midX - this.width * 0.5) / (NYC_COS_LAT * nextScale);
        this.centerLat = geoLat + (midY - this.height * 0.5) / nextScale;
        this.clampCenter();
        this.pinchPrev = { dist, midX, midY };
        this.hideTooltip();
        this.scheduleDraw();
        this.callbacks.onViewChange(this.zoom);
        return;
      }

      if (this.dragStart) {
        const dx = x - this.dragStart.x;
        const dy = y - this.dragStart.y;
        if (!this.dragStart.moved && Math.hypot(dx, dy) >= 4) {
          this.dragStart.moved = true;
        }
        if (this.dragStart.moved) {
          const scale = this.baseScale * this.zoom;
          this.centerLon = this.dragStart.lon - dx / (NYC_COS_LAT * scale);
          this.centerLat = this.dragStart.lat + dy / scale;
          this.clampCenter();
          this.hideTooltip();
          this.scheduleDraw();
          this.callbacks.onViewChange(this.zoom);
        }
        return;
      }
    }

    // Hover hit-testing (no buttons pressed)
    const hit = findHitTarget(this.hitTargets, x, y);
    if (hit) {
      this.canvas.style.cursor = "pointer";
      if (!this.hovered || this.hovered.kind !== hit.kind || this.hovered.index !== hit.index) {
        this.showTooltip(hit);
      }
    } else {
      this.canvas.style.cursor = "grab";
      this.hideTooltip();
    }
  };

  private onPointerUp = (e: PointerEvent): void => {
    const rect = this.canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    const wasClick = Boolean(this.dragStart && !this.dragStart.moved && this.activePointers.size === 1);

    this.activePointers.delete(e.pointerId);
    if (this.activePointers.size === 0) {
      this.dragStart = null;
      this.pinchPrev = null;
      this.canvas.style.cursor = "grab";
    }

    if (wasClick) {
      const hit = findHitTarget(this.hitTargets, x, y);
      if (hit) {
        if (hit.kind === "grid") {
          const cell = this.state.gridCells[hit.index];
          if (cell) this.callbacks.onClickGrid(hit.index, cell);
        } else {
          const stop = this.state.stops[hit.index];
          if (stop) this.callbacks.onClickStop(hit.index, stop);
        }
      }
    }
  };

  private onPointerLeave = (): void => {
    if (this.activePointers.size === 0) {
      this.hideTooltip();
    }
  };

  private bindEvents(): void {
    this.canvas.addEventListener("wheel", this.onWheel, { passive: false });
    this.canvas.addEventListener("pointerdown", this.onPointerDown);
    this.canvas.addEventListener("pointermove", this.onPointerMove);
    this.canvas.addEventListener("pointerup", this.onPointerUp);
    this.canvas.addEventListener("pointercancel", this.onPointerUp);
    this.canvas.addEventListener("pointerleave", this.onPointerLeave);
  }

  private unbindEvents(): void {
    this.canvas.removeEventListener("wheel", this.onWheel);
    this.canvas.removeEventListener("pointerdown", this.onPointerDown);
    this.canvas.removeEventListener("pointermove", this.onPointerMove);
    this.canvas.removeEventListener("pointerup", this.onPointerUp);
    this.canvas.removeEventListener("pointercancel", this.onPointerUp);
    this.canvas.removeEventListener("pointerleave", this.onPointerLeave);
  }
}
