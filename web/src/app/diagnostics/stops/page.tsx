import type { Metadata } from "next";

import { StopsView } from "@/app/diagnostics/stops/stops-view";
import { PageIntro } from "@/components/story/page-parts";
import { readMeta, readView } from "@/data/load";
import { stopIndex, stopRoute } from "@/data/schemas";

export const metadata: Metadata = { title: "Stop reliability" };

export default function Page() {
  const meta = readMeta();
  const indexFile = `stops/${meta.modes[0].key}/index.json`;
  const index = readView(indexFile, stopIndex);
  const routeFile = `stops/${meta.modes[0].key}/${index.data.routes[0].file}`;
  return (
    <>
      <PageIntro section="Diagnostics" title="How dependable is a route at your stop, hour by hour?">
        Pick a route and a stop to see how often it arrived on time, how late it typically was, and
        how sure the estimate is. Both service days are pooled.
      </PageIntro>
      <StopsView
        meta={meta}
        initialIndex={{ file: indexFile, ...index }}
        initialRoute={{ file: routeFile, ...readView(routeFile, stopRoute) }}
      />
    </>
  );
}
