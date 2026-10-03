import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { ROUTES } from "./helpers";

const WIDTHS = [
  { name: "mobile", width: 375, height: 812 },
  { name: "desktop", width: 1280, height: 900 },
];

for (const viewport of WIDTHS) {
  for (const route of ROUTES) {
    test(`${route} has no serious or critical accessibility violations (${viewport.name})`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await page.goto(route);
      await page.waitForLoadState("networkidle");
      const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
      const blocking = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
      expect(blocking.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(" | ")}`)).toEqual([]);
    });
  }
}

test("filters and table views work from the keyboard alone", async ({ page }) => {
  await page.goto("/reliability/on-time/");
  const subway = page.getByTestId("mode-subway");
  await subway.focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/mode=subway/);
  const toggle = page.getByRole("button", { name: "Show as table" }).first();
  await toggle.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("table").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Show as chart" }).first()).toHaveAttribute("aria-pressed", "true");
});

test("the skip link moves focus to the content", async ({ page }) => {
  await page.goto("/");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
});
