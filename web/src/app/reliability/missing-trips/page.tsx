import type { Metadata } from "next";

import { MissingTripsView } from "@/app/reliability/missing-trips/missing-trips-view";
import { PageIntro } from "@/components/story/page-parts";
import { readMeta, readView } from "@/data/load";
import { missingTrips } from "@/data/schemas";

export const metadata: Metadata = { title: "Missing trips" };

export default function Page() {
  const meta = readMeta();
  const file = `missing-trips/${meta.modes[0].key}-${meta.days[0].key}.json`;
  return (
    <>
      <PageIntro section="Reliability" title="Was every scheduled trip actually run?">
        Each trip in the timetable gets exactly one outcome, from what the real-time feed reported.
      </PageIntro>
      <MissingTripsView meta={meta} initial={{ file, ...readView(file, missingTrips) }} />
    </>
  );
}
