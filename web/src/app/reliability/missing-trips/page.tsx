import type { Metadata } from "next";

import { MissingTripsView } from "@/app/reliability/missing-trips/missing-trips-view";
import { PageIntro } from "@/components/story/page-parts";
import { readMeta, readView } from "@/data/load";
import { missingTrips } from "@/data/schemas";

export const metadata: Metadata = { title: "Trip delivery" };

export default function Page() {
  const meta = readMeta();
  const file = `missing-trips/${meta.modes[0].key}-${meta.days[0].key}.json`;
  return (
    <>
      <PageIntro section="Reliability" title="Did every scheduled trip show up running in the feed?">
        Each trip in the timetable gets exactly one outcome, from what the real-time feed reported. A trip the feed never
        showed running most likely did not run, but the feed is evidence, not proof: a trip that ran under an ID the
        timetable does not know is counted as never reported.
      </PageIntro>
      <MissingTripsView meta={meta} initial={{ file, ...readView(file, missingTrips) }} />
    </>
  );
}
