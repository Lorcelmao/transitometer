import type { Overview } from "@/data/schemas";

const SEQ = ["var(--seq-1)", "var(--seq-2)", "var(--seq-3)", "var(--seq-4)", "var(--seq-5)"];
const BANDS = ["0–20 %", "20–40 %", "40–60 %", "60–80 %", "80–100 %"];
// The intro sweep starts where the subway began: the Battery, at the southern tip of Manhattan.
const ORIGIN = { lat: 40.7033, lon: -74.017 };

/**
 * The overview's opening graphic: every located stop of both modes, binned into ~670 m cells
 * (Python, views.hero_map) and coloured by the share of their inferred arrivals that were on time.
 * Rendered as static SVG on the server, so it costs no JavaScript and shows without it. On the
 * first visit of a session the map is revealed outward from the Battery (.intro-sweep).
 */
export function HeroNetwork({ hero }: { hero: Overview["hero"] }) {
  const cells = hero.cells.map(([lat, lon, events, share, sufficient]) => ({ lat, lon, events, share, sufficient }));
  const lats = cells.map((c) => c.lat);
  const lons = cells.map((c) => c.lon);
  const [minLat, maxLat, minLon, maxLon] = [Math.min(...lats), Math.max(...lats), Math.min(...lons), Math.max(...lons)];
  const squeeze = Math.cos((((minLat + maxLat) / 2) * Math.PI) / 180);
  const scale = 600 / ((maxLon - minLon) * squeeze);
  const project = (lat: number, lon: number) => [(lon - minLon) * squeeze * scale + 10, (maxLat - lat) * scale + 10];
  const width = 620;
  const height = Math.round((maxLat - minLat) * scale + 20);
  const [ox, oy] = project(ORIGIN.lat, ORIGIN.lon);
  // One path per colour (each cell a circle drawn as two arcs): a handful of DOM nodes, not ~1,500.
  const paths = new Map<string, string[]>();
  for (const c of cells) {
    const [x, y] = project(c.lat, c.lon);
    const r = (2.7 + Math.min(1.6, Math.sqrt(c.events) / 160)).toFixed(2);
    const fill = c.sufficient ? SEQ[c.share === null ? 0 : Math.min(4, Math.floor(c.share * 5))] : "var(--rule)";
    const d = `M${(x - Number(r)).toFixed(1)},${y.toFixed(1)}a${r},${r} 0 1,0 ${(2 * Number(r)).toFixed(2)},0a${r},${r} 0 1,0 ${(-2 * Number(r)).toFixed(2)},0`;
    paths.set(fill, [...(paths.get(fill) ?? []), d]);
  }
  const origin = { "--ox": `${((ox / width) * 100).toFixed(1)}%`, "--oy": `${((oy / height) * 100).toFixed(1)}%` } as React.CSSProperties;
  return (
    <figure className="m-0">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={hero.caption} className="h-auto w-full">
        {/* The intro: one circular reveal growing from the Battery (a single animated element). */}
        <g className="intro-sweep" style={origin}>
          {[...paths].map(([fill, ds]) => (
            <path key={fill} d={ds.join("")} fill={fill} />
          ))}
        </g>
      </svg>
      <figcaption className="mt-3 space-y-2 text-xs text-muted-ink">
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1" aria-hidden="true">
          {BANDS.map((band, i) => (
            <span key={band} className="inline-flex items-center gap-1 font-mono">
              <span className="inline-block size-2.5 rounded-full" style={{ background: SEQ[i] }} />
              {band}
            </span>
          ))}
          <span className="font-mono">on time</span>
        </span>
        <span className="block">{hero.caption}</span>
      </figcaption>
    </figure>
  );
}

const STATIONS = ["Archive", "Kafka", "Spark", "Delta Lake", "Checked", "This site"];

/** The pipeline as a line diagram: stations are its stages, drawn in once on the first visit. */
export function HeroLine() {
  return (
    <div className="relative mt-8 max-w-xl" aria-label="Pipeline: archived feeds, Kafka, Spark, Delta Lake, checked against a reference, this site">
      <svg viewBox="0 0 500 14" aria-hidden="true" className="h-3.5 w-full overflow-visible" preserveAspectRatio="none">
        <line
          className="intro-line"
          x1="7"
          x2="493"
          y1="7"
          y2="7"
          stroke="var(--link)"
          strokeWidth="3"
          style={{ "--length": "486" } as React.CSSProperties}
        />
      </svg>
      <ol className="absolute inset-x-0 -top-0.5 flex justify-between" aria-hidden="true">
        {STATIONS.map((station, i) => (
          <li key={station} className="flex w-0 flex-col items-center">
            <span
              className="intro-dot block size-4 rounded-full border-2 border-ink bg-paper"
              style={{ "--delay": `${250 + i * 180}ms` } as React.CSSProperties}
            />
          </li>
        ))}
      </ol>
      <ol className="mt-2 flex justify-between font-mono text-[10px] uppercase tracking-wider text-muted-ink sm:text-[11px]">
        {STATIONS.map((station, i) => (
          <li key={station} className={`w-0 whitespace-nowrap ${i === 0 ? "text-left" : i === STATIONS.length - 1 ? "flex justify-end" : "flex justify-center"}`}>
            <span className={i % 2 === 1 ? "hidden sm:inline" : ""}>{station}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}
