import { readFile } from "node:fs/promises";

import { test, expect } from "@playwright/test";

import {
  GOLDEN_CSV,
  detectTarget,
  openNewTestPage,
  register,
  startGuardedApp,
  uploadApprovedDataset,
} from "./helpers";

/**
 * A report is the run leaving the product, so this test reads the downloaded
 * file rather than a rendered panel: the HTML must contain the verdict and the
 * weighted score on its own, with no GreenLit and no network around it.
 */
test("a finished run exports a self-contained HTML report with its verdict", async ({ page }) => {
  test.setTimeout(240_000);
  const app = await startGuardedApp();
  try {
    await register(page, "Report Reader", `report${Date.now()}@example.com`);
    const dataset = await uploadApprovedDataset(page, `Report golden ${Date.now()}`, GOLDEN_CSV);

    await openNewTestPage(page);
    await detectTarget(page, app);
    await page.selectOption('[data-testid="run-dataset"]', { label: dataset.label });
    await page.click('[data-testid="run-test"]');

    await expect(page.getByTestId("run-verdict")).toBeVisible({ timeout: 120_000 });
    await expect(page.getByTestId("run-verdict-word")).toHaveText("Go");

    const download = page.waitForEvent("download");
    await page.click('[data-testid="export-html"]');
    const file = await download;
    expect(file.suggestedFilename()).toMatch(/^greenlit-run-.+\.html$/);

    const path = await file.path();
    expect(path, "the browser wrote the export to disk").toBeTruthy();
    const body = await readFile(path as string, "utf8");

    // The verdict, its score and the rule that produced it.
    expect(body).toContain("GO");
    expect(body).toContain("Weighted score");
    expect(body).toContain("1.00");
    expect(body).toContain("GO threshold 0.80");
    // Self-contained: inline style only, no external request of any kind.
    expect(body).toContain("<style>");
    expect(body).not.toContain("<link");
    expect(body).not.toContain('src="http');
    // The setup the run executed with.
    expect(body).toContain("Connector");
    expect(body).toContain(dataset.label.split(" · ")[0]);
    expect(body).toContain("Metrics");
  } finally {
    await app.close();
  }
});
