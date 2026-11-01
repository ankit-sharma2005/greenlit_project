import { readFile } from "node:fs/promises";

import { test, expect } from "@playwright/test";

import {
  GOLDEN_CSV,
  TARGET_HOST,
  detectTarget,
  openNewTestPage,
  register,
  startGuardedApp,
  startStreamingApp,
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

/**
 * A real company chatbot streams its answer, and testing somebody else's app
 * needs their permission first. Both are exercised through the page a user sees.
 */
test("a streamed answer is joined into a verdict and permission is required", async ({ page }) => {
  test.setTimeout(240_000);
  const app = await startStreamingApp();
  try {
    await register(page, "Stream Reader", `stream${Date.now()}@example.com`);
    const dataset = await uploadApprovedDataset(page, `Stream golden ${Date.now()}`, GOLDEN_CSV);

    await openNewTestPage(page);

    // A remote target is refused until the permission box is ticked.
    await page.fill('[data-testid="target-url"]', "https://chat.example.com/ask");
    await page.click('[data-testid="start-test"]');
    await expect(page.getByRole("alert")).toContainText(
      "Confirm that you own this application or have permission",
    );
    await expect(page.getByTestId("detect-result")).toHaveCount(0);

    // The streaming app on this computer: SSE, joined by the connector.
    await page.fill('[data-testid="target-url"]', `http://${TARGET_HOST}:${app.port}/chat`);
    await page.check("#runs-on-my-computer");
    await expect(page.getByTestId("permission-block")).toHaveCount(0);
    await page.click('[data-testid="advanced-connector"] summary');
    await page.selectOption('[data-testid="response-format"]', "sse");
    // Attack probes against this fixture are not the point of this test.
    await page.getByLabel("Safety", { exact: true }).uncheck();
    await page.click('[data-testid="start-test"]');
    await expect(page.getByTestId("detect-result")).toBeVisible({ timeout: 60_000 });

    await page.selectOption('[data-testid="run-dataset"]', { label: dataset.label });
    await page.click('[data-testid="run-test"]');

    // Only a joined stream can match the golden answers, so a GO proves it.
    await expect(page.getByTestId("run-verdict")).toBeVisible({ timeout: 120_000 });
    await expect(page.getByTestId("run-verdict-word")).toHaveText("Go");
    await expect(page.getByTestId("run-verdict-score")).toHaveText("1.00");
  } finally {
    await app.close();
  }
});
