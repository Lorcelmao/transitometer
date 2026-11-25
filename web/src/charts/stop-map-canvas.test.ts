import { describe, expect, it } from "vitest";

import {
  computeBaseScale,
  computeGeoBounds,
  findHitTarget,
  lonLatToPixel,
  pixelToLonLat,
  viewportToBbox,
  type HitTarget,
  type MapViewport,
} from "@/charts/stop-map-canvas";

describe("stop-map-canvas geometry and hit testing", () => {
  const sampleGeo = {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        geometry: {
          type: "Polygon",
          coordinates: [
            [
              [-74.25, 40.5],
              [-73.7, 40.5],
              [-73.7, 40.91],
              [-74.25, 40.91],
              [-74.25, 40.5],
            ],
          ],
        },
      },
    ],
  };

  it("extracts exact GeoJSON bounds and round-trips pixel projection", () => {
    const bounds = computeGeoBounds(sampleGeo);
    expect(bounds).toEqual([-74.25, -73.7, 40.5, 40.91]);
    const vp: MapViewport = {
      width: 1000,
      height: 580,
      centerLon: -73.975,
      centerLat: 40.705,
      zoom: 3.2,
      baseScale: computeBaseScale(1000, 580, bounds),
    };
    const [px, py] = lonLatToPixel(-73.985, 40.758, vp);
    const [lon, lat] = pixelToLonLat(px, py, vp);
    expect(lon).toBeCloseTo(-73.985, 6);
    expect(lat).toBeCloseTo(40.758, 6);

    const bbox = viewportToBbox(vp, 0.1);
    expect(bbox[0]).toBeLessThan(-73.985);
    expect(bbox[1]).toBeGreaterThan(-73.985);
    expect(bbox[2]).toBeLessThan(40.758);
    expect(bbox[3]).toBeGreaterThan(40.758);
  });

  it("prefers critical stops over overlapping reliable stops at the same pixel", () => {
    const targets: HitTarget[] = [
      { kind: "stop", index: 1, lon: -73.98, lat: 40.75, px: 100, py: 100, radius: 4, priority: 1 },
      { kind: "stop", index: 2, lon: -73.98, lat: 40.75, px: 100, py: 100, radius: 4, priority: 5 },
    ];
    expect(findHitTarget(targets, 100, 100)?.index).toBe(2);
    expect(findHitTarget(targets, 200, 200)).toBeNull();
  });
});
