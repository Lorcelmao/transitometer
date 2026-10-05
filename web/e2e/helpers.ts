import fs from "node:fs";
import path from "node:path";

import { expect, type Page } from "@playwright/test";

export const ROUTES = [
  "/",
  "/reliability/on-time/",
  "/reliability/headways/",
  "/reliability/missing-trips/",
  "/diagnostics/route-scorecards/",
  "/diagnostics/stops/",
  "/diagnostics/map/",
  "/diagnostics/delay/",
  "/diagnostics/early-warning/",
  "/data/feed-health/",
  "/data/validation/",
  "/about/",
];

/** The display strings both frontends must show (written by `python tasks.py web-data`). */
export const PARITY: Record<string, unknown> = JSON.parse(
  fs.readFileSync(path.resolve(__dirname, "../../showcase/contract/parity-expected.json"), "utf8"),
);

export type FigureParity = { key: string; display: string }[];

/** Choose a mode and a service day with the page's own controls (as a visitor would). */
export async function chooseFilters(page: Page, mode: string, day?: string) {
  const toggle = page.getByTestId(`mode-${mode}`);
  // Clicking the selected item of a single toggle group would deselect it; only click to change.
  if ((await toggle.getAttribute("data-state")) !== "on") await toggle.click();
  await expect(toggle).toHaveAttribute("data-state", "on");
  if (day) {
    await page.getByTestId("day-select").click();
    await page.getByTestId(`day-${day}`).click();
    await expect(page.getByTestId("day-select")).toContainText(String(Number(day.slice(6))));
  }
}

/** Failures that matter: page exceptions, and data files that did not load. */
export function watchFailures(page: Page): string[] {
  const failures: string[] = [];
  page.on("pageerror", (error) => failures.push(`page error: ${error.message}`));
  page.on("response", (response) => {
    // Data and evidence files only (Windows builds of Next.js 16 also emit 404s for route
    // prefetches, vercel/next.js#92339; navigation still works, and Linux builds are unaffected).
    if (response.status() >= 400 && /\/(data|evidence)\/.*\.json/.test(response.url())) {
      failures.push(`${response.status()} ${response.url()}`);
    }
  });
  return failures;
}
