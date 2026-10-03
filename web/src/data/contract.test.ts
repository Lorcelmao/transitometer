/**
 * The committed JSON (written by `python tasks.py web-data`) satisfies the site's schemas, and the
 * site's navigation matches the pages the export registers.
 */
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";
import type * as z from "zod/mini";

import { NAV } from "@/components/site/nav";
import * as schemas from "@/data/schemas";

const DATA = path.resolve(__dirname, "../../public/data");
const read = (file: string) => JSON.parse(fs.readFileSync(path.join(DATA, file), "utf8"));
const files = (dir: string) =>
  fs.readdirSync(path.join(DATA, dir)).filter((f) => f.endsWith(".json")).map((f) => `${dir}/${f}`);

const BY_FOLDER: Record<string, z.ZodMiniType> = {
  "on-time": schemas.onTime,
  headways: schemas.headways,
  "missing-trips": schemas.missingTrips,
  scorecards: schemas.scorecards,
  "early-warning": schemas.earlyWarning,
};

describe("exported JSON matches the site's contract", () => {
  it.each(Object.entries(BY_FOLDER))("%s", (folder, schema) => {
    for (const file of files(folder)) expect(() => schemas.parseView(file, read(file), schema)).not.toThrow();
  });

  it("delay summaries and segment lists", () => {
    for (const file of files("delay")) {
      const schema = file.endsWith("-segments.json") ? schemas.segments : schemas.delay;
      expect(() => schemas.parseView(file, read(file), schema)).not.toThrow();
    }
  });

  it("every stop route file of both modes", () => {
    for (const mode of ["bus", "subway"]) {
      const index = schemas.parseView("index", read(`stops/${mode}/index.json`), schemas.stopIndex).data;
      for (const route of index.routes) {
        const file = `stops/${mode}/${route.file}`;
        expect(() => schemas.parseView(file, read(file), schemas.stopRoute)).not.toThrow();
      }
    }
  });

  it("site-wide files", () => {
    expect(() => schemas.parseView("meta", read("meta.json"), schemas.meta)).not.toThrow();
    expect(() => schemas.parseView("overview", read("overview.json"), schemas.overview)).not.toThrow();
    expect(() => schemas.parseView("feed", read("feed-health.json"), schemas.feedHealth)).not.toThrow();
    expect(() => schemas.parseView("validation", read("validation.json"), schemas.validation)).not.toThrow();
  });

  it("rejects a file whose numbers were renamed or retyped", () => {
    const body = read("on-time/bus-20260922.json");
    body.data.routes[0].on_time_share = "47 %";
    expect(() => schemas.parseView("mutated", body, schemas.onTime)).toThrow(/does not match/);
    body.schema = "transitometer.web/2";
    expect(() => schemas.parseView("mutated", body, schemas.onTime)).toThrow(/not a transitometer.web\/1/);
  });

  it("navigation links are exactly the export's page routes", () => {
    const pages = schemas.parseView("meta", read("meta.json"), schemas.meta).data.pages;
    const linked = Object.fromEntries(NAV.flatMap((g) => g.links.map((l) => [l.page, l.href])));
    for (const [page, info] of Object.entries(pages)) {
      if (page === "overview") expect(info.route).toBe("/");
      else expect(linked[page]).toBe(info.route);
    }
  });
});
