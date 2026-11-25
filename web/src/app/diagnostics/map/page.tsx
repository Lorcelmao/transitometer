import type { Metadata } from "next";
import { preload } from "react-dom";

import { MapView } from "@/app/diagnostics/map/map-view";
import { PageIntro } from "@/components/story/page-parts";
import { readMeta, readView } from "@/data/load";
import { overview, stopMapGrid } from "@/data/schemas";

export const metadata: Metadata = { title: "Stop map" };

export default function Page() {
  const meta = readMeta();
  const initialBus = readView("map-grid/bus.json", stopMapGrid);
  const initialSubway = readView("map-grid/subway.json", stopMapGrid);
  const overviewData = readView("overview.json", overview).data;
  const arrivalWeightedNote =
    overviewData.findings.find((f) => f.key === "modes")?.headline ?? "";

  // Start fetching the lightweight city-wide grid and NYC borough geometry in parallel with JS.
  preload("/data/map-grid/bus.json", { as: "fetch", crossOrigin: "anonymous" });
  preload("/basemap/nyc-boroughs.geojson", { as: "fetch", crossOrigin: "anonymous" });

  // Strip the 1,502 grid cells and 328 subway stops from RSC HTML so the document stays compact;
  // summary KPIs and the top-50 table rows arrive in HTML for instant first paint and table parity.
  const busMeta = { ...initialBus.data, grid_cells: [], stops: [] };
  const subwayMeta = { ...initialSubway.data, grid_cells: [], stops: [] };

  return (
    <>
      <PageIntro section="Diagnostics" title="Where in the city were arrivals least reliable?">
        On-time share across every reported NYC bus stop and subway station, all routes and hours
        pooled over both days. Red marks corridors under 30 % on time; zoom in to inspect
        individual stops.
      </PageIntro>
      <MapView
        meta={meta}
        busInitial={busMeta}
        subwayInitial={subwayMeta}
        arrivalWeightedNote={arrivalWeightedNote}
        source={initialBus.source}
      />
    </>
  );
}
