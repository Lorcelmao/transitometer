import Link from "next/link";

import { HomeGlance } from "@/app/home-glance";
import { NAV } from "@/components/site/nav";
import { ProvenanceLine } from "@/components/site/provenance-line";
import { readMeta, readView } from "@/data/load";
import { overview as overviewSchema } from "@/data/schemas";

const STEPS = [
  {
    title: "Real archived feeds",
    text: "MTA GTFS-Realtime snapshots (bus trip updates, bus GPS positions, subway trip updates) for two service days, plus the published timetables.",
  },
  {
    title: "Kafka replay",
    text: "Every snapshot is re-encoded as protobuf and replayed through Kafka, keyed by trip or vehicle, with per-snapshot lineage.",
  },
  {
    title: "Spark Structured Streaming → Delta Silver",
    text: "Decoded, deduplicated within an event-time watermark, bad messages dead-lettered, every count reconciled.",
  },
  {
    title: "Spark batch → Delta Gold",
    text: "Stop arrivals inferred, matched to the timetable, and turned into the reliability and feed-quality tables.",
  },
  {
    title: "Checked, then published",
    text: "Every Gold table is compared with an independent DuckDB implementation of the same rules; this site serves the validated snapshot.",
  },
];

const BLURBS: Record<string, string> = {
  "on-time": "Which routes reach their stops on schedule, hour by hour.",
  headways: "Where vehicles bunch and leave long gaps behind them.",
  "missing-trips": "Which scheduled trips never ran.",
  scorecards: "Route rankings with honest confidence intervals.",
  stops: "How dependable a route is at your stop, by hour.",
  map: "Every stop in the city, coloured by how often it was on time.",
  delay: "Whether late trips started late or lost time on the way.",
  "early-warning": "Could trouble have been predicted halfway through a trip?",
  "feed-health": "How trustworthy the real-time feeds themselves are.",
  validation: "The evidence behind every number on this site.",
};

export default function Home() {
  const meta = readMeta();
  const { data: overview, source } = readView("overview.json", overviewSchema);
  const { integrity, parity } = overview.trust;
  const { silver, gold } = meta.snapshot.validation;
  return (
    <>
      <section className="pt-12 md:pt-20">
        <p className="text-xs font-medium uppercase tracking-widest text-accent-red">
          New York bus and subway · two service days
        </p>
        <h1 className="mt-3 max-w-4xl font-display text-5xl leading-[1.05] md:text-7xl">
          Was the promised transit service actually delivered?
        </h1>
        <p className="mt-6 max-w-2xl text-lg">
          Transitometer compares New York&apos;s bus and subway timetables with what the real-time feeds
          reported, to measure punctuality, bunching, missing trips, and the quality of the feeds
          themselves. Built on real archived data replayed through a streaming pipeline; not a live
          service and not an official MTA product.
        </p>
      </section>

      <HomeGlance meta={meta} overview={overview} />
      <div className="mt-4">
        <ProvenanceLine source={source} />
      </div>

      <section aria-labelledby="how" className="mt-20">
        <h2 id="how" className="border-b border-ink pb-2 font-display text-3xl">
          How it works
        </h2>
        <ol className="mt-6 grid gap-6 md:grid-cols-5">
          {STEPS.map((step, i) => (
            <li key={step.title} className="border-t border-rule pt-3">
              <span className="num text-sm text-accent-red">{String(i + 1).padStart(2, "0")}</span>
              <h3 className="mt-1 font-semibold">{step.title}</h3>
              <p className="mt-1 text-sm text-muted-ink">{step.text}</p>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="trust" className="mt-20">
        <h2 id="trust" className="border-b border-ink pb-2 font-display text-3xl">
          Why the numbers can be trusted
        </h2>
        <dl className="mt-6 grid gap-8 md:grid-cols-3">
          <div className="border-t-2 border-ink pt-2">
            <dt className="text-xs font-medium uppercase tracking-wider text-muted-ink">Source integrity</dt>
            <dd className="num mt-1 text-3xl" data-testid="trust-integrity">
              {integrity.available ? integrity.archive_rows_display : "not yet measured"}
            </dd>
            <dd className="mt-2 text-sm text-muted-ink">
              archive rows reached the lakehouse unchanged ({integrity.status}): counts equal at every hop,
              sampled messages identical field by field.
            </dd>
          </div>
          <div className="border-t-2 border-ink pt-2">
            <dt className="text-xs font-medium uppercase tracking-wider text-muted-ink">Golden-reference parity</dt>
            <dd className="num mt-1 text-3xl" data-testid="trust-parity">
              {parity.available ? parity.display : "not yet measured"}
            </dd>
            <dd className="mt-2 text-sm text-muted-ink">
              Spark tables equal an independent DuckDB implementation of the same rules (Silver{" "}
              <span className="num">
                {silver.passed}/{silver.total}
              </span>
              , Gold{" "}
              <span className="num">
                {gold.passed}/{gold.total}
              </span>
              ).
            </dd>
          </div>
          <div className="border-t-2 border-ink pt-2">
            <dt className="text-xs font-medium uppercase tracking-wider text-muted-ink">Validated run</dt>
            <dd className="num mt-1 text-3xl">{meta.snapshot.validated_on}</dd>
            <dd className="mt-2 text-sm text-muted-ink">
              recorded in commit <span className="num">{meta.snapshot.validated_commit.slice(0, 7)}</span>; every
              file of this snapshot is listed with its SHA-256.{" "}
              <Link href="/data/validation/">See the evidence</Link>
            </dd>
          </div>
        </dl>
      </section>

      <section aria-labelledby="explore" className="mt-20">
        <h2 id="explore" className="border-b border-ink pb-2 font-display text-3xl">
          Explore
        </h2>
        <div className="mt-6 grid gap-10 md:grid-cols-3">
          {NAV.map((group) => (
            <div key={group.section}>
              <h3 className="text-xs font-medium uppercase tracking-widest text-muted-ink">{group.section}</h3>
              <ul className="mt-3 space-y-4">
                {group.links.map((link) => (
                  <li key={link.href}>
                    <Link href={link.href} className="font-display text-xl">
                      {link.label}
                    </Link>
                    <p className="text-sm text-muted-ink">{BLURBS[link.page]}</p>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>
    </>
  );
}
