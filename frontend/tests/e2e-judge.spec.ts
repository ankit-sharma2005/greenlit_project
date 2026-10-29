import { test, expect } from "@playwright/test";

import {
  ADMIN_EMAIL,
  GOLDEN_ANSWERS,
  GOLDEN_CSV,
  createJudgeProfile,
  createProvider,
  login,
  openNewTestPage,
  startFakeProvider,
  uploadApprovedDataset,
} from "./helpers";

/**
 * A judged run: a saved judge profile, a fake provider for both the app under
 * test and the judge, and the verdict card naming which model scored it.
 *
 * The admin account is used because providers are admin-only; judge profiles are
 * per-user, so this profile only affects the runs started here.
 */
test("a judged run names the judge model and rubric on the verdict card", async ({ page }) => {
  test.setTimeout(180_000);
  const stamp = Date.now();
  const judgeModel = `fake-judge-${stamp}`;
  const appModel = `fake-app-${stamp}`;
  const provider = await startFakeProvider({
    answers: GOLDEN_ANSWERS,
    judgeReply: { score: 1, reason: "The answer states the expected fact.", confidence: 0.95 },
  });
  try {
    await login(page, ADMIN_EMAIL);
    const baseUrl = `http://127.0.0.1:${provider.port}/v1`;
    await createProvider(page, { name: `Judge app ${stamp}`, model: appModel, baseUrl });
    const judgeProviderId = await createProvider(page, {
      name: `Judge model ${stamp}`,
      model: judgeModel,
      baseUrl,
    });
    // The first profile is selected automatically, so new runs use it.
    await createJudgeProfile(page, {
      name: `Judge profile ${stamp}`,
      providerId: judgeProviderId,
      model: judgeModel,
    });
    const dataset = await uploadApprovedDataset(page, `Judge golden ${stamp}`, GOLDEN_CSV);

    await openNewTestPage(page);
    await page.selectOption('[data-testid="connector-select"]', "prompt_app");
    await page.selectOption('[data-testid="prompt-provider-select"]', {
      label: `Judge app ${stamp}`,
    });
    await expect(page.getByTestId("prompt-app-model")).toHaveValue(appModel);
    await page.fill(
      '[data-testid="prompt-system-prompt"]',
      "You are a concise assistant. Answer in one sentence.",
    );
    await page.selectOption('[data-testid="prompt-app-dataset"]', { label: dataset.label });
    await page.click('[data-testid="start-test"]');

    // Judging must not change a clean verdict, only add the provenance.
    await expect(page.getByTestId("run-verdict")).toBeVisible({ timeout: 120_000 });
    await expect(page.getByTestId("run-verdict-word")).toHaveText("Go");
    await expect(page.getByTestId("run-verdict-judge")).toContainText(judgeModel);
    await expect(page.getByTestId("run-verdict-judge")).toContainText("rubric");
    await expect(page.getByTestId("run-verdict-judge-skipped")).toHaveCount(0);
    await expect(page.getByTestId("run-metrics")).toContainText("answer quality");
  } finally {
    await provider.close();
  }
});
