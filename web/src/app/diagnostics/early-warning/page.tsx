import type { Metadata } from "next";

import { EarlyWarningView } from "@/app/diagnostics/early-warning/early-warning-view";
import { PageIntro } from "@/components/story/page-parts";
import { readMeta, readView } from "@/data/load";
import { earlyWarning } from "@/data/schemas";

export const metadata: Metadata = { title: "Early warning" };

export default function Page() {
  const meta = readMeta();
  const file = `early-warning/${meta.modes[0].key}.json`;
  return (
    <>
      <PageIntro section="Diagnostics" title="Could an operator have seen trouble coming?">
        Halfway through each trip, two simple rules predict whether it will <strong>end late</strong> or
        get <strong>bunched</strong> later. Each rule is compared with a naive baseline that only looks at
        the trip&apos;s current state, on a day the rules were not tuned on.
      </PageIntro>
      <EarlyWarningView meta={meta} initial={{ file, ...readView(file, earlyWarning) }} />
    </>
  );
}
