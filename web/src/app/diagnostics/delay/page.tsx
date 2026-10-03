import type { Metadata } from "next";

import { DelayView } from "@/app/diagnostics/delay/delay-view";
import { PageIntro } from "@/components/story/page-parts";
import { readMeta, readView } from "@/data/load";
import { delay, segments } from "@/data/schemas";

export const metadata: Metadata = { title: "Where delay builds up" };

export default function Page() {
  const meta = readMeta();
  const mode = meta.modes[0].key;
  const file = `delay/${mode}-${meta.days[0].key}.json`;
  const segmentsFile = `delay/${mode}-segments.json`;
  return (
    <>
      <PageIntro section="Diagnostics" title="Did late trips start late, or lose time on the way?">
        Each trip&apos;s delay at its last observed stop splits exactly into the delay it already had at
        its first observed stop and the time it gained segment by segment.
      </PageIntro>
      <DelayView
        meta={meta}
        initial={{ file, ...readView(file, delay) }}
        segments={{ file: segmentsFile, ...readView(segmentsFile, segments) }}
      />
    </>
  );
}
