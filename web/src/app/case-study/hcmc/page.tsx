import type { Metadata } from "next";

import { HcmcView } from "@/app/case-study/hcmc/hcmc-view";
import { PageIntro } from "@/components/story/page-parts";
import { readView } from "@/data/load";
import { hcmcCoverage } from "@/data/schemas";

export const metadata: Metadata = {
  title: "HCMC bus coverage (case study)",
  description:
    "Static 400 m walk-shed coverage and open-data quality baseline for Ho Chi Minh City's bus network, computed in DuckDB Spatial from OpenStreetMap (ODbL 1.0).",
};

export default function Page() {
  const { data } = readView("hcmc/core_hcmc.json", hcmcCoverage);
  return (
    <>
      <PageIntro section="Case study (BR11)" title="Where does Ho Chi Minh City's bus network leave coverage gaps?">
        To test how Transitometer&apos;s static data pipeline transfers to a city without public GTFS-Realtime feeds,
        we converted OpenStreetMap bus relations for <strong>Ho Chi Minh City</strong> into a frequency-based GTFS
        snapshot and computed deduplicated 400 m walk-shed coverage in DuckDB Spatial (
        <code className="mono-id text-xs">EPSG:32648</code>).
      </PageIntro>
      <HcmcView initial={data} />
    </>
  );
}
