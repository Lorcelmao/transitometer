import type { Metadata } from "next";
import Link from "next/link";

import { REPOSITORY } from "@/components/site/nav";
import { ProvenanceLine } from "@/components/site/provenance-line";
import { STREAMLIT_URL } from "@/components/site/site-footer";
import { PageIntro } from "@/components/story/page-parts";
import { readMeta, readView } from "@/data/load";
import { overview as overviewSchema } from "@/data/schemas";

export const metadata: Metadata = {
  title: "About",
  description: "What Transitometer does, why it was built, the decisions behind it and the trade-offs they cost.",
};

/** One row of the supporting facts under the writeup. */
function Fact({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <div className="border-t border-rule pt-2">
      <dt className="text-xs font-medium uppercase tracking-widest text-muted-ink">{term}</dt>
      <dd className="mt-1">{children}</dd>
    </div>
  );
}

/**
 * The project writeup (kept under 1,000 characters: the two paragraphs in the article), then
 * supporting facts. Figures come from the exported views, like every other number on the site.
 */
export default function Page() {
  const meta = readMeta();
  const { data, source } = readView("overview.json", overviewSchema);
  const { pipeline } = data;
  return (
    <>
      <article aria-labelledby="writeup-title" data-testid="writeup">
        <PageIntro section="About · project writeup" title="Why I built Transitometer" titleId="writeup-title">
          Transitometer is a reliability app built from archived New York MTA GTFS-Realtime feeds. It began as my Data
          Engineering course project; I kept developing it into a product because raw transit feeds are hard to inspect
          and easy to misread (a trip missing from the feed is not proof it never ran). It turns two days of feed
          observations into evidence that riders, planners and feed maintainers can explore: punctuality, bunching, trip
          delivery, where delay builds up and feed quality, each with its sample size and caveats.
        </PageIntro>
        <p className="mt-6 max-w-prose">
          I made the product and architecture decisions. Archived snapshots are replayed through Kafka into Spark, and a
          separate DuckDB implementation of the same rules checks Spark&apos;s output. The heavy pipeline stays on one
          machine; only a validated snapshot is published, as a static Next.js site on Vercel. That trades live data for
          near-zero hosting cost, fast pages and results reproducible from the repository. A Streamlit console remains
          for deeper technical inspection.
        </p>
        <p className="mt-4 text-sm text-muted-ink">
          By <a href="https://github.com/Lorcelmao">Loc Huynh</a>, sole developer
        </p>
      </article>

      <section aria-labelledby="glance" className="mt-14">
        <h2 id="glance" className="border-b border-ink pb-2 font-display text-2xl">
          At a glance
        </h2>
        <dl className="mt-4 grid gap-x-10 gap-y-5 text-sm md:grid-cols-2">
          <Fact term="Data">
            Archived MTA feeds for {meta.days.map((d) => d.label).join(" and ")}:{" "}
            <span className="num">{pipeline.archive_rows}</span> rows of bus and subway trip updates and bus positions.
          </Fact>
          <Fact term="Checked">
            <span className="num">{pipeline.gold}</span> Spark output tables equal the separate DuckDB implementation,
            floats within a written tolerance. <Link href="/data/validation/">See the evidence</Link>.
          </Fact>
          <Fact term="What the feeds can and cannot say">
            Arrival times are inferred from the feeds&apos; predictions. A trip absent from the feed is evidence, not proof,
            that it did not run.
          </Fact>
          <Fact term="Where it runs">
            Kafka, Spark and Delta Lake run locally from the repository. This site is static files on Vercel; nothing here
            is computed live.
          </Fact>
        </dl>
      </section>

      <nav aria-label="Where to look next" className="mt-10 border-y border-rule py-4">
        <ul className="flex flex-col gap-3 text-sm sm:flex-row sm:flex-wrap sm:gap-x-8">
          <li>
            <Link href="/">Explore the findings</Link>
          </li>
          <li>
            <Link href="/data/validation/">See how the numbers were checked</Link>
          </li>
          <li>
            <a href={REPOSITORY}>Source code on GitHub</a>
          </li>
          {STREAMLIT_URL ? (
            <li>
              <a href={STREAMLIT_URL}>Analyst console (Streamlit)</a>
            </li>
          ) : null}
        </ul>
      </nav>
      <div className="mt-8">
        <ProvenanceLine source={source} />
      </div>
    </>
  );
}
