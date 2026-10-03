import type { Metadata } from "next";

import { ScorecardsView } from "@/app/diagnostics/route-scorecards/scorecards-view";
import { PageIntro } from "@/components/story/page-parts";
import { readMeta, readView } from "@/data/load";
import { scorecards } from "@/data/schemas";

export const metadata: Metadata = { title: "Route scorecards" };

export default function Page() {
  const meta = readMeta();
  const file = `scorecards/${meta.modes[0].key}.json`;
  return (
    <>
      <PageIntro section="Diagnostics" title="Which routes are reliably on time, and how sure can we be?">
        Each route&apos;s on-time share comes with a <strong>95 % confidence interval</strong>: a short
        line means a solid estimate, a long one means few observations. Where two routes&apos; lines
        overlap, the data cannot tell them apart. Both service days are pooled.
      </PageIntro>
      <ScorecardsView meta={meta} initial={{ file, ...readView(file, scorecards) }} />
    </>
  );
}
