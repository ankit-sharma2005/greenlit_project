import { test, expect } from "@playwright/test";

import {
  GOLDEN_ANSWERS,
  GOLDEN_CSV,
  WEB,
  createJudgeProfile,
  createProvider,
  ensureAdmin,
  login,
  openNewTestPage,
  startFakeProvider,
  uploadApprovedDataset,
} from "./helpers";

/**
 * Human labels and calibration (M7): a judge that is unsure puts its cases in the
 * review queue, a reviewer labels them, and the page reports Cohen's kappa.
 *
 * The judge here answers with confidence 0.2, so every case is "unsure" and the
 * queue is predictable without a real model.
 */
test("labelling queued cases makes kappa appear", async ({ page }) => {
  test.setTimeout(240_000);
  const stamp = Date.now();
  const model = `calibration-model-${stamp}`;
  const provider = await startFakeProvider({
    answers: GOLDEN_ANSWERS,
    judgeReply: { score: 0.9, reason: "Probably right.", confidence: 0.2 },
  });
  try {
    await ensureAdmin();
    await login(page, "admin@example.com");
    const baseUrl = `http://127.0.0.1:${provider.port}/v1`;
    const providerId = await createProvider(page, {
      name: `Calibration app ${stamp}`,
      model,
      baseUrl,
    });
    await createJudgeProfile(page, {
      name: `Unsure judge ${stamp}`,
      providerId,
      model,
    });
    const dataset = await uploadApprovedDataset(page, `Calibration golden ${stamp}`, GOLDEN_CSV);

    await openNewTestPage(page);
    await page.selectOption('[data-testid="connector-select"]', "prompt_app");
    await page.selectOption('[data-testid="prompt-provider-select"]', {
      label: `Calibration app ${stamp}`,
    });
    await page.fill('[data-testid="prompt-system-prompt"]', "Answer in one sentence.");
    await page.selectOption('[data-testid="prompt-app-dataset"]', { label: dataset.label });
    await page.click('[data-testid="start-test"]');
    await expect(page.getByTestId("run-verdict")).toBeVisible({ timeout: 120_000 });
    // An unsure judge is REVIEW, never a silent GO (rule 3).
    await expect(page.getByTestId("run-verdict-word")).toHaveText("Review");

    await page.goto(`${WEB}/calibration`);
    await expect(page.getByTestId("calibration-empty")).toBeVisible();
    const rows = page.getByTestId("review-row");
    await expect(rows).toHaveCount(2);
    await expect(rows.first()).toContainText("the judge was unsure about this case");

    // Label the rows that are still unlabelled, so a reload cannot reorder them
    // under the assertions. One agrees with the judge, one does not, which makes
    // kappa defined (here 0: judge pass, reviewer pass and fail).
    const unlabelled = page
      .getByTestId("review-row")
      .filter({ hasNot: page.getByTestId("review-label") });
    await unlabelled.first().getByTestId("review-pass").click();
    await expect(page.getByTestId("review-label")).toHaveCount(1);
    await expect(unlabelled).toHaveCount(1);
    await unlabelled.first().getByTestId("review-fail").click();
    await expect(page.getByTestId("review-label")).toHaveCount(2);
    await expect(page.getByTestId("calibration-kappa")).toBeVisible();
    await expect(page.getByTestId("calibration-reading")).toContainText("kappa");
    await expect(page.getByTestId("calibration-labelled")).toHaveText("2");

    // The labels are real state: reload and they are still there.
    await page.reload();
    await expect(page.getByTestId("calibration-labelled")).toHaveText("2");
  } finally {
    await provider.close();
  }
});
