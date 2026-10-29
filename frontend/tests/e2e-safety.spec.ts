import { test, expect } from "@playwright/test";

import {
  GOLDEN_CSV,
  detectTarget,
  openNewTestPage,
  register,
  startEchoApp,
  startGuardedApp,
  uploadApprovedDataset,
  type FakeApp,
} from "./helpers";

/** Attach the two-case golden dataset and run the app to its verdict. */
async function runAgainstApp(page: import("@playwright/test").Page, app: FakeApp): Promise<void> {
  const dataset = await uploadApprovedDataset(page, `Safety golden ${Date.now()}`, GOLDEN_CSV);
  await openNewTestPage(page);
  await detectTarget(page, app);
  await page.selectOption('[data-testid="run-dataset"]', { label: dataset.label });
  await page.click('[data-testid="run-test"]');
  await expect(page.getByTestId("run-verdict")).toBeVisible({ timeout: 120_000 });
}

/**
 * A vulnerable app repeats the planted marker, so the canary attacks succeed.
 * Those are the critical cases: a leaked secret is a hard NO-GO (spec 8.3).
 */
test("an app that leaks the canary gets NO-GO from the safety gate", async ({ page }) => {
  test.setTimeout(180_000);
  const app = await startEchoApp();
  try {
    await register(page, "Safety Leaky", `safety-leak${Date.now()}@example.com`);
    await runAgainstApp(page, app);

    await expect(page.getByTestId("run-verdict-word")).toHaveText("No-Go");
    await expect(page.getByTestId("run-verdict-reason")).toContainText("Hard gate failed");
    await expect(page.getByTestId("run-verdict-reason")).toContainText("attack_resisted");

    // The dedicated Safety section names the marker and the critical failures.
    await expect(page.getByTestId("safety-section")).toBeVisible();
    // The section names the cases that repeated the planted marker; the marker
    // itself is only in the metric's own details.
    await expect(page.getByTestId("safety-leaks")).toContainText("planted marker");
    await expect(page.getByTestId("safety-leaks")).toContainText("sl-01");
    await expect(page.getByTestId("safety-critical-detail")).toContainText("hard NO-GO");
    await expect(page.getByTestId("safety-attacks")).toHaveText("44");
  } finally {
    await app.close();
  }
});

/** The same probes against a guarded app: every attack resisted, nothing over-refused. */
test("a guarded app passes the same attacks and reaches GO", async ({ page }) => {
  test.setTimeout(180_000);
  const app = await startGuardedApp();
  try {
    await register(page, "Safety Guarded", `safety-guard${Date.now()}@example.com`);
    await runAgainstApp(page, app);

    await expect(page.getByTestId("run-verdict-word")).toHaveText("Go");
    await expect(page.getByTestId("run-verdict-reason")).toContainText("GO threshold 0.80");

    await expect(page.getByTestId("safety-attacks")).toHaveText("44");
    await expect(page.getByTestId("safety-resisted")).toContainText("44 of 44");
    await expect(page.getByTestId("safety-critical")).toHaveText("0");
    await expect(page.getByTestId("safety-over-refusal")).toHaveText("0.00");
    await expect(page.getByTestId("safety-leaks")).toHaveCount(0);
  } finally {
    await app.close();
  }
});
