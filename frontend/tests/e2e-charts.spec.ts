/**
 * Charts on the run pages, proved in a real browser.
 *
 * A finished run draws the gauge, the metric bars and the data tables; a metric the
 * run never measured is an empty slot reading "not measured", never a zero bar; the
 * document does not scroll sideways at 375px; and the Results page shows the trend
 * once two runs exist.
 */

import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { API, WEB, register } from "./helpers";

const SCREENS = path.resolve(process.cwd(), "..", "local-prompts", "screens");

interface DemoSetup {
  dataset_id: string;
  dataset_version_id: string;
  good_url: string;
  broken_url: string;
}

async function finished(page: Page, runId: string): Promise<void> {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const response = await page.request.get(`${API}/api/v1/runs/${runId}`);
    const run = (await response.json()) as { state: string };
    if (["completed", "failed", "cancelled"].includes(run.state)) {
      expect(run.state, "the demo run must finish").toBe("completed");
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error(`Run ${runId} did not finish in two minutes.`);
}

async function startDemoRun(page: Page, demo: DemoSetup, name: string): Promise<string> {
  const created = await page.request.post(`${API}/api/v1/runs`, {
    data: {
      name,
      entry_point: "http_endpoint",
      target: demo.good_url,
      body_template: '{"question": {{input}}}',
      answer_path: "answer",
      context_path: "context",
      timeout_seconds: 60,
      allow_private_targets: true,
      dataset_version_id: demo.dataset_version_id,
    },
  });
  expect(created.status(), await created.text()).toBe(202);
  const run = (await created.json()) as { id: string };
  await finished(page, run.id);
  return run.id;
}

test("a finished run draws its charts, says not measured, and keeps the page still at 375px", async ({
  page,
}) => {
  test.setTimeout(300_000);
  await register(page, "Charts User", `charts${Date.now()}@example.com`);

  const setup = await page.request.post(`${API}/api/v1/demo/load`);
  expect(setup.status(), await setup.text()).toBe(200);
  const demo = (await setup.json()) as DemoSetup;
  await startDemoRun(page, demo, "Charts — first run");

  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(`${WEB}/results`);
  await page.getByTestId("run-history-open").first().click();

  // The block exists, and each chart is an image with its own text alternative.
  await expect(page.getByTestId("run-charts")).toBeVisible();
  const gauge = page.getByTestId("verdict-gauge-svg");
  await expect(gauge).toHaveAttribute("role", "img");
  await expect(gauge).toHaveAttribute("aria-label", /Weighted score \d\.\d\d/);
  const bars = page.getByTestId("metric-bars-svg");
  await expect(bars).toHaveAttribute("aria-label", /Metric scores/);

  // An unmeasured metric is a dashed slot labelled "not measured", with no bar for it.
  const unmeasured = page.locator('[data-testid^="metric-unmeasured-"]').first();
  await expect(unmeasured).toBeVisible();
  const name = (await unmeasured.getAttribute("data-testid"))!.replace("metric-unmeasured-", "");
  await expect(page.getByTestId(`metric-bar-${name}`)).toHaveCount(0);
  await expect(page.getByTestId("metric-bars-svg")).toContainText("not measured");

  // The data table carries the same value, not a zero.
  await page.getByTestId("metric-bars").getByText("Show data table").click();
  const table = page.getByTestId("metric-bars-table");
  await expect(table).toContainText("not measured");
  const label = name.replaceAll("_", " ");
  await expect(table).toContainText(label);

  await page.screenshot({ path: path.join(SCREENS, "after-charts-run-1280x800-dark.png") });

  // Light theme: the fills come from tokens, so the same chart must render.
  await page.evaluate(() => document.documentElement.setAttribute("data-theme", "light"));
  await page.screenshot({ path: path.join(SCREENS, "after-charts-run-1280x800-light.png") });
  await page.evaluate(() => document.documentElement.setAttribute("data-theme", "dark"));

  // 375px: main.page is the only scroller and the document does not scroll sideways.
  await page.setViewportSize({ width: 375, height: 800 });
  const overflow = await page.evaluate(() => {
    const documentElement = document.documentElement;
    const main = document.querySelector("main.page");
    if (!main) throw new Error("main.page is missing");
    return {
      horizontal: documentElement.scrollWidth > documentElement.clientWidth,
      mainOverflowY: getComputedStyle(main).overflowY,
    };
  });
  expect(overflow.horizontal).toBe(false);
  expect(overflow.mainOverflowY).toBe("auto");
  await page.screenshot({ path: path.join(SCREENS, "after-charts-run-375x800-dark.png") });
});

test("the Results page draws the score trend once two runs are finished", async ({ page }) => {
  test.setTimeout(300_000);
  await register(page, "Trend User", `trend${Date.now()}@example.com`);

  const setup = await page.request.post(`${API}/api/v1/demo/load`);
  expect(setup.status(), await setup.text()).toBe(200);
  const demo = (await setup.json()) as DemoSetup;
  await startDemoRun(page, demo, "Trend — first");
  await startDemoRun(page, demo, "Trend — second");

  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(`${WEB}/results`);
  await expect(page.getByTestId("run-trend")).toBeVisible();
  const svg = page.getByTestId("run-trend-svg");
  await expect(svg).toHaveAttribute("aria-label", /Scores of 2 finished runs/);
  await expect(page.getByTestId("run-trend-point-0")).toBeVisible();
  await page.screenshot({ path: path.join(SCREENS, "after-charts-results-trend-1280x800-dark.png") });
});
