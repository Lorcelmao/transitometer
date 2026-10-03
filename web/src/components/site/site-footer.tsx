import Link from "next/link";

import type { Meta } from "@/data/schemas";

export const STREAMLIT_URL = process.env.NEXT_PUBLIC_STREAMLIT_URL ?? "";

/** What runs where, the data licence, and where to look further. */
export function SiteFooter({ meta }: { meta: Meta }) {
  const { snapshot } = meta;
  return (
    <footer className="mt-20 border-t border-ink bg-panel">
      <div className="mx-auto grid max-w-6xl gap-8 px-4 py-10 text-sm md:grid-cols-3 md:px-6">
        <section aria-labelledby="where">
          <h2 id="where" className="text-xs font-medium uppercase tracking-widest text-muted-ink">
            What runs where
          </h2>
          <p className="mt-2">
            This site is a static snapshot of the Spark pipeline&apos;s validated Gold tables (run {" "}
            <span className="num">{snapshot.validated_commit.slice(0, 7)}</span>, {snapshot.validated_on}). The
            streaming pipeline (Kafka, Spark Structured Streaming, Delta Lake) runs locally from the
            repository; nothing here is computed live.
          </p>
        </section>
        <section aria-labelledby="data">
          <h2 id="data" className="text-xs font-medium uppercase tracking-widest text-muted-ink">
            Data
          </h2>
          <p className="mt-2">
            Real archived MTA GTFS-Realtime feeds (via the gtfsrt.io archive) and MTA static timetables,
            used under the MTA Terms of Use. Not an official MTA product and not endorsed by the MTA.
          </p>
        </section>
        <section aria-labelledby="more">
          <h2 id="more" className="text-xs font-medium uppercase tracking-widest text-muted-ink">
            Look further
          </h2>
          <ul className="mt-2 space-y-1">
            <li>
              <Link href="/data/validation/">How the numbers were checked</Link>
            </li>
            <li>
              <a href={meta.repository}>Source code and pipeline</a>
            </li>
            {STREAMLIT_URL ? (
              <li>
                <a href={STREAMLIT_URL}>Analyst console (Streamlit, same snapshot)</a>
              </li>
            ) : null}
          </ul>
        </section>
      </div>
    </footer>
  );
}
