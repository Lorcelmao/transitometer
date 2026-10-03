import type { Metadata } from "next";
import { Suspense } from "react";

import { FeedHealthView } from "@/app/data/feed-health/feed-health-view";
import { PageIntro } from "@/components/story/page-parts";
import { readMeta, readView } from "@/data/load";
import { feedHealth } from "@/data/schemas";

export const metadata: Metadata = { title: "Feed health" };

export default function Page() {
  const meta = readMeta();
  const { data, source } = readView("feed-health.json", feedHealth);
  return (
    <>
      <PageIntro section="Data quality" title="How trustworthy were the real-time feeds themselves?">
        Every number on this site depends on the feeds, so their quality is measured too. Each feed is
        checked every day against fixed thresholds; the <strong>score</strong> is the share of checks
        passed.
      </PageIntro>
      <Suspense fallback={null}>
        <FeedHealthView meta={meta} data={data} source={source} />
      </Suspense>
    </>
  );
}
