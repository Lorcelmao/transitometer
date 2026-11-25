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
  description: "What Transitometer does, why it exists, the decisions behind it and the trade-offs they cost.",
};

function Fact({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-rule bg-paper p-4">
      <dt className="text-xs font-semibold text-muted-ink">{term}</dt>
      <dd className="mt-1.5 text-sm leading-relaxed text-ink">{children}</dd>
    </div>
  );
}

/**
 * The project writeup, then supporting facts. Figures come from the exported views, like every
 * other number on the site.
 */
export default function Page() {
  const meta = readMeta();
  const { data, source } = readView("overview.json", overviewSchema);
  const { pipeline } = data;
  return (
    <div className="space-y-6">
      <article aria-labelledby="writeup-title" data-testid="writeup" className="space-y-4">
        <PageIntro section="Project overview" title="About Transitometer" titleId="writeup-title">
          Transitometer is a reliability scorecard built from archived New York MTA GTFS-Realtime feeds. It began as a
          Data Engineering course project and grew into a public product, because raw transit feeds are hard to inspect
          and easy to misread (a trip missing from the feed is not proof it never ran). It turns two days of feed
          observations into evidence that riders, planners and feed maintainers can explore: punctuality, bunching,
          trip delivery, where delay builds up and feed quality, each with its sample size and caveats.
        </PageIntro>
        <div className="rounded-xl border border-rule bg-surface p-5 shadow-xs">
          <p className="max-w-prose text-[15px] leading-relaxed text-ink">
            Archived snapshots are replayed through Kafka into Spark, and a separate DuckDB implementation of the same
            rules checks Spark&apos;s output. The heavy pipeline stays on one machine; only a validated snapshot is
            published, as a static Next.js site on Vercel. That trades live data for near-zero hosting cost, fast pages
            and results reproducible from the repository. A Streamlit console remains for deeper technical inspection.
          </p>
        </div>
      </article>

      <section aria-labelledby="about-glance" className="rounded-xl border border-rule bg-surface p-5 shadow-xs">
        <h2 id="about-glance" className="text-lg font-bold tracking-tight text-ink">
          At a glance
        </h2>
        <dl className="mt-4 grid gap-3.5 md:grid-cols-2">
          <Fact term="Data">
            Archived MTA feeds for {meta.days.map((d) => d.label).join(" and ")}:{" "}
            <span className="num font-semibold">{pipeline.archive_rows}</span> rows of bus and subway trip updates and
            bus positions.
          </Fact>
          <Fact term="Checked">
            <span className="num font-semibold">{pipeline.gold}</span> Spark output tables equal the separate DuckDB
            implementation, floats within a written tolerance.{" "}
            <Link href="/data/validation/" prefetch={false}>
              See the evidence
            </Link>
            .
          </Fact>
          <Fact term="What the feeds can and cannot say">
            Arrival times are inferred from the feeds&apos; predictions. A trip absent from the feed is evidence, not
            proof, that it did not run.
          </Fact>
          <Fact term="Where it runs">
            Kafka, Spark and Delta Lake run locally from the repository. This site is static files on Vercel; nothing
            here is computed live.
          </Fact>
        </dl>
      </section>

      <nav
        aria-label="Where to look next"
        className="rounded-xl border border-rule bg-surface px-5 py-4 shadow-xs"
      >
        <ul className="flex flex-col gap-3 text-sm font-medium sm:flex-row sm:flex-wrap sm:gap-x-7">
          <li>
            <Link href="/" prefetch={false}>
              Explore the findings
            </Link>
          </li>
          <li>
            <Link href="/data/validation/" prefetch={false}>
              See how the numbers were checked
            </Link>
          </li>
          <li>
            <Link href="/case-study/hcmc/" prefetch={false}>
              HCMC bus coverage case study
            </Link>
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

      <div className="rounded-xl border border-rule bg-surface px-5 py-3 shadow-xs">
        <ProvenanceLine source={source} />
      </div>
    </div>
  );
}
