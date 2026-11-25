import type { Overview } from "@/data/schemas";

const SEQ = ["var(--seq-1)", "var(--seq-2)", "var(--seq-3)", "var(--seq-4)", "var(--seq-5)"];
const BANDS = ["0 to 20 %", "20 to 40 %", "40 to 60 %", "60 to 80 %", "80 to 100 %"];
// The intro sweep starts where the subway began: the Battery, at the southern tip of Manhattan.
const ORIGIN = { lat: 40.7033, lon: -74.017 };

/**
 * Every located stop of both modes, binned into ~670 m cells (Python, views.hero_map) and
 * coloured by the share of inferred arrivals that were on time. Rendered as static SVG on the
 * server so it costs zero client JavaScript. On the first visit of a session the map reveals
 * outward from the Battery (.intro-sweep), disabled automatically under prefers-reduced-motion.
 */
export function HeroNetwork({ hero, maxHeight = 250 }: { hero: Overview["hero"]; maxHeight?: number }) {
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

  const paths = new Map<string, string[]>();
  for (const c of cells) {
    const [x, y] = project(c.lat, c.lon);
    const r = (2.7 + Math.min(1.6, Math.sqrt(c.events) / 160)).toFixed(2);
    const fill = c.sufficient ? SEQ[c.share === null ? 0 : Math.min(4, Math.floor(c.share * 5))] : "var(--rule-strong)";
    const d = `M${(x - Number(r)).toFixed(1)},${y.toFixed(1)}a${r},${r} 0 1,0 ${(2 * Number(r)).toFixed(2)},0a${r},${r} 0 1,0 ${(-2 * Number(r)).toFixed(2)},0`;
    paths.set(fill, [...(paths.get(fill) ?? []), d]);
  }
  const origin = {
    "--ox": `${((ox / width) * 100).toFixed(1)}%`,
    "--oy": `${((oy / height) * 100).toFixed(1)}%`,
  } as React.CSSProperties;

  return (
    <figure className="m-0">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={hero.caption}
        style={{ maxHeight }}
        className="mx-auto h-auto w-full"
      >
        <g className="intro-sweep" style={origin}>
          {[...paths].map(([fill, ds]) => (
            <path key={fill} d={ds.join("")} fill={fill} />
          ))}
        </g>
      </svg>
      <figcaption className="mt-2.5 flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-xs text-muted-ink">
        {BANDS.map((band, i) => (
          <span key={band} className="inline-flex items-center gap-1.5">
            <span className="inline-block size-2.5 rounded-full" style={{ background: SEQ[i] }} aria-hidden="true" />
            <span className="num">{band}</span>
          </span>
        ))}
      </figcaption>
    </figure>
  );
}
