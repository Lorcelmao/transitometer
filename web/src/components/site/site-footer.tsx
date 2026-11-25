import Link from "next/link";

import type { Meta } from "@/data/schemas";

// The hosted analyst console; NEXT_PUBLIC_STREAMLIT_URL overrides it (for example for a fork).
export const STREAMLIT_URL = process.env.NEXT_PUBLIC_STREAMLIT_URL || "https://transitometer.streamlit.app/";

/** Compact dashboard footer: snapshot provenance, data licence, and further links. */
export function SiteFooter({ meta }: { meta: Meta }) {
  const { snapshot } = meta;
  return (
    <footer className="mt-auto border-t border-rule bg-surface px-4 py-5 text-xs text-muted-ink md:px-7">
      <div className="mx-auto flex max-w-[1180px] flex-wrap items-center justify-between gap-x-6 gap-y-2">
        <p>
          Static snapshot of validated Spark Gold tables (run{" "}
          <span className="mono-id font-medium text-ink">{snapshot.validated_commit.slice(0, 7)}</span>,{" "}
          {snapshot.validated_on}). Not a live service and not an official MTA product.
        </p>
        <p className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <span>Data: MTA GTFS-RT (gtfsrt.io) and static timetables</span>
          <Link href="/data/validation/" prefetch={false} className="inline-flex min-h-7 items-center py-0.5">
            Validation evidence
          </Link>
          <Link href="/about/" prefetch={false} className="inline-flex min-h-7 items-center py-0.5">
            Limits and methodology
          </Link>
          {STREAMLIT_URL ? (
            <a href={STREAMLIT_URL} className="inline-flex min-h-7 items-center py-0.5">
              Analyst console (Streamlit)
            </a>
          ) : null}
          <a href={meta.repository} className="inline-flex min-h-7 items-center py-0.5">
            GitHub
          </a>
        </p>
      </div>
    </footer>
  );
}
