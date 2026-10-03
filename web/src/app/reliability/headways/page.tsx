import type { Metadata } from "next";

import { HeadwaysView } from "@/app/reliability/headways/headways-view";
import { PageIntro } from "@/components/story/page-parts";
import { readMeta, readView } from "@/data/load";
import { headways } from "@/data/schemas";

export const metadata: Metadata = { title: "Headways and bunching" };

export default function Page() {
  const meta = readMeta();
  const file = `headways/${meta.modes[0].key}-${meta.days[0].key}.json`;
  return (
    <>
      <PageIntro section="Reliability" title="Did vehicles come evenly, or in clumps?">
        Riders feel reliability as waiting time. A <strong>headway</strong> is the time between two
        consecutive vehicles of a route at a stop. Vehicles <strong>bunch</strong> when one catches up
        with the one ahead, leaving a long <strong>gap</strong> behind them.
      </PageIntro>
      <HeadwaysView meta={meta} initial={{ file, ...readView(file, headways) }} />
    </>
  );
}
