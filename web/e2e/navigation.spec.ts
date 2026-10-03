import fs from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { ROUTES, watchFailures } from "./helpers";

for (const route of ROUTES) {
  test(`${route} renders with a title, provenance and the archived-data marker`, async ({ page }) => {
    const failures = watchFailures(page);
    await page.goto(route);
    await expect(page.locator("h1")).toHaveCount(1);
    await expect(page.getByTestId("provenance").first()).toContainText("validated run");
    await expect(page.getByText(/not a live service/).first()).toBeVisible();
    expect(failures).toEqual([]);
  });
}

test("a deep link restores the filters it names", async ({ page }) => {
  await page.goto("/reliability/on-time/?mode=subway&day=20260923");
  await expect(page.getByTestId("mode-subway")).toHaveAttribute("data-state", "on");
  await expect(page.getByTestId("day-select")).toContainText("23 Sep 2026");
});

test("an invalid filter in a link falls back to the defaults", async ({ page }) => {
  await page.goto("/reliability/on-time/?mode=tram&day=19990101");
  await expect(page.getByTestId("mode-bus")).toHaveAttribute("data-state", "on");
});

test("the stop explorer loads another route's stops on demand", async ({ page }) => {
  const failures = watchFailures(page);
  await page.goto("/diagnostics/stops/");
  await page.getByTestId("route-select").click();
  await page.getByRole("option").nth(5).click();
  await expect(page).toHaveURL(/route=/);
  await expect(page.getByTestId("value-arrivals")).not.toBeEmpty();
  expect(failures).toEqual([]);
});

test("the site works with the network to third parties blocked", async ({ page }) => {
  const external: string[] = [];
  await page.route("**/*", (route) => {
    const url = new URL(route.request().url());
    if (url.hostname !== "localhost") {
      external.push(url.href);
      return route.abort();
    }
    return route.continue();
  });
  await page.goto("/reliability/on-time/");
  await expect(page.locator("h1")).toBeVisible();
  expect(external).toEqual([]);
});

test("the Content-Security-Policy of vercel.json blocks nothing the site uses", async ({ page }) => {
  const config = JSON.parse(fs.readFileSync(path.resolve(__dirname, "../vercel.json"), "utf8"));
  const csp = config.headers[0].headers.find((h: { key: string }) => h.key === "Content-Security-Policy").value;
  await page.route("**/*", async (route) => {
    const response = await route.fetch();
    await route.fulfill({ response, headers: { ...response.headers(), "content-security-policy": csp } });
  });
  await page.addInitScript(() => {
    (window as unknown as { __csp: string[] }).__csp = [];
    document.addEventListener("securitypolicyviolation", (e) =>
      (window as unknown as { __csp: string[] }).__csp.push(`${e.violatedDirective} ${e.blockedURI}`),
    );
  });
  for (const route of ["/", "/reliability/on-time/", "/diagnostics/stops/"]) {
    await page.goto(route);
    await page.mouse.wheel(0, 1500); // bring the charts into view so ECharts loads
    await page.waitForLoadState("networkidle");
    expect(await page.evaluate(() => (window as unknown as { __csp: string[] }).__csp)).toEqual([]);
  }
});

test("the intro plays once per session and never under reduced motion", async ({ browser }) => {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto("/");
  await expect(page.locator("html")).not.toHaveAttribute("data-intro", "seen");
  await page.goto("/reliability/on-time/");
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("data-intro", "seen");
  await context.close();

  const calm = await browser.newContext({ reducedMotion: "reduce" });
  const still = await calm.newPage();
  await still.goto("/");
  const animation = await still.locator(".intro-sweep").first().evaluate((el) => getComputedStyle(el).animationName);
  expect(animation).toBe("none");
  await calm.close();
});

test("section menus open and lead to their pages", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");
  await page.getByRole("button", { name: "Diagnostics" }).click();
  await page.getByRole("link", { name: /Stop map/ }).first().click();
  await expect(page).toHaveURL(/\/diagnostics\/map\/$/);
  await expect(page.getByRole("navigation", { name: "Previous and next page" })).toBeVisible();
});
