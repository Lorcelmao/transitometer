import Link from "next/link";

import type { Source } from "@/data/schemas";

/** Where a number comes from: the Gold tables, the validated run's commit and date. */
export function ProvenanceLine({ source }: { source: Source }) {
  return (
    <p className="text-xs text-muted-ink" data-testid="provenance">
      Source:{" "}
      <span className="mono-id">
        {source.tables.length ? source.tables.join(", ") : "committed result files"}
      </span>
      . Spark Gold snapshot, validated run{" "}
      <span className="mono-id">{source.snapshot_commit.slice(0, 7)}</span> ({source.validated_on}).{" "}
      <Link href="/data/validation/" prefetch={false}>
        How it was checked
      </Link>
    </p>
  );
}
