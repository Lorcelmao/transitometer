import type { Metadata } from "next";

import { OnTimeView } from "@/app/reliability/on-time/on-time-view";
import { PageIntro } from "@/components/story/page-parts";
import { readMeta, readView } from "@/data/load";
import { onTime } from "@/data/schemas";

export const metadata: Metadata = { title: "On-time performance" };

export default function Page() {
  const meta = readMeta();
  const file = `on-time/${meta.modes[0].key}-${meta.days[0].key}.json`;
  return (
    <>
      <PageIntro section="Reliability" title="How often did buses and trains arrive on schedule?">
        An arrival counts as <strong>on time</strong> when it is at most 1 minute early and at most 5
        minutes late, the MTA&apos;s own band.
      </PageIntro>
      <OnTimeView meta={meta} initial={{ file, ...readView(file, onTime) }} />
    </>
  );
}
