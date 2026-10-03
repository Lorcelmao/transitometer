import Link from "next/link";

import type { Source } from "@/data/schemas";

/** Where a number comes from: the Gold tables, the validated run's commit and date. */
export function ProvenanceLine({ source }: { source: Source }) {
  return (
    <p className="font-mono text-xs text-muted-ink" data-testid="provenance">
      Source: {source.tables.length ? source.tables.join(", ") : "committed result files"} · Spark Gold
      snapshot, validated run {source.snapshot_commit.slice(0, 7)} ({source.validated_on}) ·{" "}
      <Link href="/data/validation/">how it was checked</Link>
    </p>
  );
}
