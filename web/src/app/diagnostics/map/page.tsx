import type { Metadata } from "next";

import { MapView } from "@/app/diagnostics/map/map-view";
import { PageIntro } from "@/components/story/page-parts";
import { readMeta, readView } from "@/data/load";
import { stopMap } from "@/data/schemas";

export const metadata: Metadata = { title: "Stop map" };

export default function Page() {
  const meta = readMeta();
  const file = `map/${meta.modes[0].key}.json`;
  return (
    <>
      <PageIntro section="Diagnostics" title="Where in the city were arrivals least reliable?">
        Every stop the feeds reported, placed by its timetable coordinates and coloured by the share of
        its arrivals that were on time, all routes and hours pooled over both days. No map tiles: the
        stops themselves trace the city.
      </PageIntro>
      <MapView meta={meta} initial={{ file, ...readView(file, stopMap) }} />
    </>
  );
}
