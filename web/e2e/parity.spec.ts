/**
 * Cross-frontend parity: the site shows the display strings in showcase/contract/parity-expected.json
 * for every mode and day, reached by clicking the filters. tests/test_app_pages.py asserts the same
 * file against Streamlit, so both frontends are held to one set of numbers.
 */
import { expect, test } from "@playwright/test";

import { chooseFilters, PARITY, watchFailures, type FigureParity } from "./helpers";

const MODES = ["bus", "subway"];
const DAYS = ["20260922", "20260923"];
const PAGES: [string, string][] = [
  ["overview", "/"],
  ["headways", "/reliability/headways/"],
  ["missing-trips", "/reliability/missing-trips/"],
  ["delay", "/diagnostics/delay/"],
];

for (const [view, route] of PAGES) {
  test(`${view}: headline figures equal the parity file for every mode and day`, async ({ page }) => {
    const failures = watchFailures(page);
    await page.goto(route);
    for (const mode of MODES) {
      for (const day of DAYS) {
        await chooseFilters(page, mode, day);
        const expected = PARITY[`${view}/${mode}/${day}`] as FigureParity;
        for (const figure of expected) {
          await expect(page.getByTestId(`value-${figure.key}`)).toHaveText(figure.display);
        }
      }
    }
    expect(failures).toEqual([]);
  });
}

test("stops: the sampled stop's figures equal the parity file", async ({ page }) => {
  const sample = Object.keys(PARITY).find((k) => k.startsWith("stops/bus/"))!;
  const expected = PARITY[sample] as FigureParity;
  await page.goto("/diagnostics/stops/");
  for (const figure of expected) {
    await expect(page.getByTestId(`value-${figure.key}`)).toHaveText(figure.display);
  }
});

test("early warning: the held-out verdicts equal the parity file", async ({ page }) => {
  await page.goto("/diagnostics/early-warning/");
  for (const mode of MODES) {
    await chooseFilters(page, mode);
    const expected = PARITY[`early-warning/${mode}`] as Record<string, string>;
    for (const [outcome, verdict] of Object.entries(expected)) {
      await expect(page.getByTestId(`verdict-${outcome}`)).toContainText(verdict);
    }
  }
});

test("feed health: every feed score equals the parity file on both days", async ({ page }) => {
  await page.goto("/data/feed-health/");
  for (const day of DAYS) {
    await page.getByTestId("day-select").click();
    await page.getByTestId(`day-${day}`).click();
    const expected = PARITY[`feed-health/${day}`] as Record<string, string>;
    for (const [feed, display] of Object.entries(expected)) {
      await expect(page.getByTestId(`feed-${feed}`)).toContainText(display);
    }
  }
});

test("validation: parity, archive rows and tests equal the parity file", async ({ page }) => {
  const expected = PARITY.validation as Record<string, string>;
  await page.goto("/");
  await expect(page.getByTestId("trust-parity")).toHaveText(expected.parity);
  await expect(page.getByTestId("trust-integrity")).toHaveText(expected.archive_rows);
  await page.goto("/data/validation/");
  await expect(page.getByTestId("tests-passed")).toHaveText(expected.tests);
});

test("stop map: the least reliable stop equals the parity file in both modes", async ({ page }) => {
  await page.goto("/diagnostics/map/");
  for (const mode of MODES) {
    await chooseFilters(page, mode);
    const expected = PARITY[`map/${mode}`] as { worst: string; display: string };
    await page.getByRole("button", { name: "Show as table" }).click();
    const first = page.locator("tbody tr").first();
    await expect(first).toContainText(expected.worst);
    await expect(first).toContainText(expected.display);
    await page.getByRole("button", { name: "Show as chart" }).click();
  }
});
