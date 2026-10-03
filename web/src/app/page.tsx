import { ArrowRight, ArrowDown } from "lucide-react";
import Link from "next/link";

import { HomeGlance } from "@/app/home-glance";
import { NAV, PAGES, REPOSITORY } from "@/components/site/nav";
import { ProvenanceLine } from "@/components/site/provenance-line";
import { STREAMLIT_URL } from "@/components/site/site-footer";
import { HeroLine, HeroNetwork } from "@/components/story/hero";
import { PreviewGlyph } from "@/components/story/preview-glyph";
import { readMeta, readView } from "@/data/load";
import { overview as overviewSchema } from "@/data/schemas";

function Chapter({ number, id, title, children }: { number: string; id: string; title: string; children: React.ReactNode }) {
  return (
    <section aria-labelledby={id} className="mt-24 scroll-mt-28">
      <p className="text-xs font-medium uppercase tracking-widest text-accent-red">Chapter {number}</p>
      <h2 id={id} className="mt-1 border-b border-ink pb-3 font-display text-3xl md:text-4xl">
        {title}
      </h2>
      {children}
    </section>
  );
}

export default function Home() {
  const meta = readMeta();
  const { data: overview, source } = readView("overview.json", overviewSchema);
  const { pipeline, trust } = overview;
  const href = (page: string) => PAGES.find((p) => p.page === page)?.href ?? "/";
  const stages = [
    { name: "Archived feeds", figure: pipeline.archive_rows, unit: "archive rows", text: "Real MTA GTFS-Realtime snapshots for two service days (bus trip updates, bus GPS positions, subway trip updates) and the published timetables." },
    { name: "Kafka replay", figure: pipeline.messages, unit: "protobuf messages", text: "Every snapshot re-encoded and replayed through Kafka, keyed by trip or vehicle, with per-snapshot lineage." },
    { name: "Spark → Delta Silver", figure: pipeline.stop_events, unit: "inferred stop arrivals", text: "Structured Streaming decodes, deduplicates and dead-letters; batch jobs infer arrivals and match them to the timetable." },
    { name: "Spark → Delta Gold", figure: pipeline.gold, unit: "tables equal the reference", text: `Reliability and feed-quality tables for eight requirements, built in ${pipeline.gold_seconds ?? "—"}.` },
    { name: "This site", figure: pipeline.tests, unit: "automated tests passing", text: "A validated snapshot of Gold, served as static files; every number carries its source." },
  ];
  return (
    <>
      <section className="grid items-center gap-10 pt-10 md:pt-14 lg:grid-cols-12">
        <div className="lg:col-span-7">
          <p className="text-xs font-medium uppercase tracking-widest text-accent-red">New York bus and subway · two archived service days</p>
          <h1 className="mt-3 font-display text-5xl leading-[1.04] md:text-6xl xl:text-7xl">
            Was the promised transit service actually delivered?
          </h1>
          <p className="mt-6 max-w-2xl text-lg">
            Transitometer compares New York&apos;s bus and subway timetables with what the real-time feeds reported, to
            measure punctuality, bunching, trips that never showed up, and the quality of the feeds themselves. A streaming
            data pipeline replays real archived feeds; every result is checked against an independent reference
            implementation.
          </p>
          <HeroLine />
          <div className="mt-10 flex flex-wrap gap-3">
            <a href="#glance" className="inline-flex min-h-11 items-center gap-2 bg-ink px-4 text-sm text-paper no-underline hover:bg-ink/85">
              Explore the results <ArrowDown className="size-4" aria-hidden="true" />
            </a>
            <Link href="/data/validation/" className="inline-flex min-h-11 items-center gap-2 border border-ink px-4 text-sm text-ink no-underline hover:bg-panel">
              How it was checked
            </Link>
            <a href={REPOSITORY} className="inline-flex min-h-11 items-center gap-2 px-2 text-sm">
              Source and pipeline on GitHub
            </a>
          </div>
        </div>
        <div className="lg:col-span-5">
          <HeroNetwork hero={overview.hero} />
          <Link href="/diagnostics/map/" className="mt-2 inline-flex min-h-11 items-center gap-1 text-sm">
            Open the stop map <ArrowRight className="size-4" aria-hidden="true" />
          </Link>
        </div>
      </section>

      <HomeGlance meta={meta} overview={overview} source={source} />

      <Chapter number="2" id="findings" title="What the data shows">
        <ol className="mt-8 grid gap-x-8 gap-y-10 md:grid-cols-2">
          {overview.findings.map((f) => (
            <li key={f.key} className="reveal border-t-2 border-ink pt-3" data-testid={`finding-${f.key}`}>
              <p className="text-[11px] font-medium uppercase tracking-widest text-muted-ink">{f.kicker}</p>
              <p className="num mt-2 text-4xl text-ink">{f.value}</p>
              <p className="mt-3 font-display text-xl leading-snug">{f.headline}</p>
              <p className="mt-2 text-sm text-muted-ink">{f.detail}</p>
              <Link href={href(f.page)} className="mt-3 inline-flex min-h-11 items-center gap-1 text-sm">
                See the data <ArrowRight className="size-4" aria-hidden="true" />
              </Link>
            </li>
          ))}
        </ol>
      </Chapter>

      <Chapter number="3" id="how" title="How it works">
        <p className="mt-6 max-w-prose">
          Read the pipeline like a line diagram: each station is a stage, with the verified count of what passed through it.
        </p>
        <ol className="reveal relative mt-10 grid gap-10 md:grid-cols-5 md:gap-6">
          <span aria-hidden="true" className="absolute left-[7px] top-2 bottom-2 w-[3px] bg-link md:left-0 md:right-0 md:top-[7px] md:bottom-auto md:h-[3px] md:w-auto" />
          {stages.map((stage) => (
            <li key={stage.name} className="relative pl-8 md:pl-0 md:pt-8">
              <span aria-hidden="true" className="absolute left-0 top-0.5 block size-[17px] rounded-full border-[3px] border-ink bg-paper md:top-0" />
              <h3 className="font-semibold">{stage.name}</h3>
              <p className="num mt-1 text-2xl text-ink">{stage.figure ?? "—"}</p>
              <p className="text-xs uppercase tracking-wider text-muted-ink">{stage.unit}</p>
              <p className="mt-2 text-sm text-muted-ink">{stage.text}</p>
            </li>
          ))}
        </ol>
      </Chapter>

      <Chapter number="4" id="trust" title="Why the numbers can be trusted">
        <dl className="mt-8 grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
          <div className="reveal border-t-2 border-ink pt-2">
            <dt className="text-xs font-medium uppercase tracking-wider text-muted-ink">Source integrity</dt>
            <dd className="num mt-1 text-3xl" data-testid="trust-integrity">
              {trust.integrity.available ? trust.integrity.archive_rows_display : "not yet measured"}
            </dd>
            <dd className="mt-2 text-sm text-muted-ink">
              archive rows reached the lakehouse unchanged ({trust.integrity.status}): counts equal at every hop, sampled
              messages identical field by field.
            </dd>
          </div>
          <div className="reveal border-t-2 border-ink pt-2">
            <dt className="text-xs font-medium uppercase tracking-wider text-muted-ink">Silver parity</dt>
            <dd className="num mt-1 text-3xl" data-testid="trust-silver">
              {pipeline.silver ?? "not yet measured"}
            </dd>
            <dd className="mt-2 text-sm text-muted-ink">
              stop-event and matching tables equal an independent DuckDB implementation of the same rules.
            </dd>
          </div>
          <div className="reveal border-t-2 border-ink pt-2">
            <dt className="text-xs font-medium uppercase tracking-wider text-muted-ink">Gold parity</dt>
            <dd className="num mt-1 text-3xl" data-testid="trust-gold">
              {pipeline.gold ?? "not yet measured"}
            </dd>
            <dd className="mt-2 text-sm text-muted-ink">
              result tables for all eight requirements equal the reference, under a written tolerance policy.
            </dd>
          </div>
          <div className="reveal border-t-2 border-ink pt-2">
            <dt className="text-xs font-medium uppercase tracking-wider text-muted-ink">Automated tests</dt>
            <dd className="num mt-1 text-3xl" data-testid="trust-tests">
              {pipeline.tests ?? "not yet measured"}
            </dd>
            <dd className="mt-2 text-sm text-muted-ink">
              passing in the recorded run; both frontends are also tested against one file of expected values.
            </dd>
          </div>
        </dl>
        <p className="mt-6 text-sm text-muted-ink">
          Parity shows that two independent implementations of the same written rules agree; it does not prove the rules are
          the best possible definition. <Link href="/data/validation/">See every evidence file and its SHA-256</Link>.
        </p>
      </Chapter>

      <Chapter number="5" id="explore" title="Explore">
        <div className="mt-8 space-y-10">
          {NAV.map((group) => (
            <div key={group.section}>
              <h3 className="text-xs font-medium uppercase tracking-widest text-muted-ink">{group.section}</h3>
              <ul className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {group.links.map((link) => (
                  <li key={link.href} className="reveal">
                    <Link
                      href={link.href}
                      className="group flex h-full flex-col border border-rule bg-paper p-4 no-underline transition-colors duration-200 hover:border-ink hover:bg-panel/50"
                    >
                      <PreviewGlyph kind={link.preview} className="h-16 w-full border-b border-rule pb-3" />
                      <span className="mt-3 flex items-center justify-between gap-2 font-display text-xl text-ink">
                        {link.label}
                        <ArrowRight className="size-4 shrink-0 text-muted-ink transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
                      </span>
                      <span className="mt-1 text-sm text-muted-ink">{link.blurb}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </Chapter>

      <Chapter number="6" id="about" title="About this project">
        <div className="mt-8 grid gap-10 lg:grid-cols-12">
          <div className="space-y-4 lg:col-span-7">
            <p>
              Transitometer is a streaming and lakehouse data pipeline that measures bus and subway reliability from real
              GTFS-Realtime feeds. Archived MTA snapshots are replayed through <strong>Kafka</strong>, decoded and
              deduplicated by <strong>Spark Structured Streaming</strong> into <strong>Delta Lake</strong>, turned into
              reliability tables by Spark batch jobs, and checked table by table against an independent{" "}
              <strong>DuckDB</strong> implementation of the same rules.
            </p>
            <p>
              Both public apps read the validated snapshot through one Python layer, so a metric is defined once: this site
              (Next.js, static) and an analyst console (Streamlit). Charts here only display numbers computed there.
            </p>
            <h3 className="pt-2 font-semibold">Limits worth knowing</h3>
            <ul className="list-disc space-y-1 pl-5 text-sm">
              <li>Two archived service days ({meta.days.map((d) => d.label).join(" and ")}), replayed: not a live service.</li>
              <li>Arrival times are inferred from the feeds&apos; predictions; the feeds do not report actual arrivals.</li>
              <li>A trip absent from the feed counts as never reported, which is evidence, not proof, that it did not run.</li>
              <li>Not an official MTA product; source data used under the MTA Terms of Use.</li>
            </ul>
          </div>
          <aside className="space-y-3 border-t-2 border-ink pt-3 lg:col-span-5">
            <p className="text-xs font-medium uppercase tracking-widest text-muted-ink">Links</p>
            <ul className="space-y-2">
              <li>
                <a href={REPOSITORY}>Source code, pipeline and results on GitHub</a>
              </li>
              {STREAMLIT_URL ? (
                <li>
                  <a href={STREAMLIT_URL}>Analyst console (Streamlit, same snapshot)</a>
                </li>
              ) : null}
              <li>
                <Link href="/data/validation/">Evidence files and validation</Link>
              </li>
            </ul>
            <p className="pt-2 text-sm text-muted-ink">
              Built by <a href="https://github.com/Lorcelmao">Lorcelmao</a>. Stack: Python, Kafka, PySpark Structured
              Streaming, Delta Lake, DuckDB, Streamlit, Next.js.
            </p>
          </aside>
        </div>
        <div className="mt-10">
          <ProvenanceLine source={source} />
        </div>
      </Chapter>
    </>
  );
}
