import type { Metadata } from "next";
import Link from "next/link";

import { REPOSITORY } from "@/components/site/nav";
import { ProvenanceLine } from "@/components/site/provenance-line";
import { STREAMLIT_URL } from "@/components/site/site-footer";
import { PageIntro } from "@/components/story/page-parts";
import { readView } from "@/data/load";
import { overview as overviewSchema } from "@/data/schemas";

export const metadata: Metadata = {
  title: "About",
  description: "What Transitometer does, why it was built, the decisions behind it and the trade-offs they cost.",
};

function Part({ id, label, children }: { id: string; label: string; children: React.ReactNode }) {
  return (
    <section aria-labelledby={id} className="mt-10 border-t-2 border-ink pt-3 md:grid md:grid-cols-12 md:gap-8">
      <h2 id={id} className="text-xs font-medium uppercase tracking-widest text-muted-ink md:col-span-3 md:pt-1">
        {label}
      </h2>
      <p className="mt-2 max-w-prose md:col-span-9 md:mt-0">{children}</p>
    </section>
  );
}

/** The short build story: what the product does, which decisions were the author's, and what they cost. */
export default function Page() {
  // Figures come from the exported overview view, like every other number on the site.
  const { data, source } = readView("overview.json", overviewSchema);
  const { pipeline } = data;
  return (
    <>
      <PageIntro section="About" title="Why I built Transitometer">
        Transitometer asks whether New York&apos;s buses and subways ran the service they promised. It turns two days
        of archived MTA GTFS-Realtime feeds (<span className="num">{pipeline.archive_rows}</span> rows) into on-time,
        bunching, trip-delivery and stop-reliability views for planners, operators and riders.
      </PageIntro>
      <p className="mt-4 text-sm text-muted-ink">
        By <a href="https://github.com/Lorcelmao">Loc Huynh</a>, sole developer
      </p>

      <Part id="decisions" label="Decisions I made">
        I picked the problem and built it alone. My calls: replay the archive through Kafka into Spark and Delta Lake,
        as a live feed would arrive; reimplement the same rules in DuckDB SQL and require Spark to match it (
        <span className="num">{pipeline.gold}</span> tables); define each metric once in Python so both frontends agree.
      </Part>

      <Part id="trade-offs" label="Trade-offs">
        The heavy pipeline runs on one machine, and this site is a static snapshot of a validated run. No live data,
        but it is free to host, fast, and every number traces to a reproducible run. Streamlit stays as a separate
        analyst console. Arrivals are inferred from predictions, so pages report what the feeds showed, not confirmed
        operations.
      </Part>

      <nav aria-label="Where to look next" className="mt-12 border-y border-rule py-4">
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
