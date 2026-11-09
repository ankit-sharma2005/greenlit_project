/**
 * Settings → Providers and models: the three per-job model defaults.
 *
 * Proves the panel saves to the account, survives a reload, warns when the
 * generator is the judge and refuses to save that choice without an explicit
 * confirmation, and never puts a provider key on the page.
 */

import path from "node:path";

import { expect, test } from "@playwright/test";

import { API, WEB, createProvider, register, startFakeProvider } from "./helpers";

const SCREENS = path.resolve(process.cwd(), "..", "local-prompts", "screens");
const SENTINEL_KEY = "sk-e2e-sentinel-never-render";

test("the three model defaults save, persist and warn about a self-grading generator", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const fake = await startFakeProvider();
  try {
    const email = `models${Date.now()}@example.com`;
    await register(page, "Models User", email);

    const providerId = await createProvider(page, {
      name: `E2E models ${Date.now()}`,
      model: "llama3",
      baseUrl: `http://127.0.0.1:${fake.port}/v1`,
    });
    // A key on the provider must never appear in the page, whatever the panel does.
    await page.request.patch(`${API}/api/v1/providers/${providerId}`, {
      data: { api_key: SENTINEL_KEY },
    });

    await page.goto(`${WEB}/settings`);
    await page.getByTestId("settings-tab-providers-and-models").click();
    await expect(page.getByTestId("model-defaults")).toBeVisible();

    for (const role of ["judge", "target", "generator"]) {
      await page.selectOption(`[data-testid="model-defaults-${role}-provider"]`, providerId);
    }
    const judgeModel = page.getByTestId("model-defaults-judge-model");
    await judgeModel.fill("llama3");
    await page.getByTestId("model-defaults-target-model").fill("llama3");
    await page.getByTestId("model-defaults-generator-model").fill("mixtral");

    await expect(page.getByTestId("model-defaults-warning")).toHaveCount(0);
    await page.getByTestId("model-defaults-save").click();
    await expect(page.getByTestId("model-defaults-notice")).toContainText("Saved to your account");

    // Reload: the values come back from the account, not from component state.
    await page.reload();
    await page.getByTestId("settings-tab-providers-and-models").click();
    await expect(page.getByTestId("model-defaults-generator-model")).toHaveValue("mixtral");
    await expect(page.getByTestId("model-defaults-judge-provider")).toHaveValue(providerId);

    // Same provider and model as the judge: a warning, and no saving without a tick.
    await page.getByTestId("model-defaults-generator-model").fill("llama3");
    await expect(page.getByTestId("model-defaults-warning")).toBeVisible();
    await expect(page.getByTestId("model-defaults-save")).toBeDisabled();
    await page.screenshot({ path: path.join(SCREENS, "after-model-defaults-warning-1280x800-dark.png") });
    await page.getByTestId("model-defaults-confirm").check();
    await expect(page.getByTestId("model-defaults-save")).toBeEnabled();

    // No key text anywhere on the page.
    const body = await page.locator("body").innerText();
    expect(body).not.toContain(SENTINEL_KEY);
    expect(body).not.toContain("sk-");

    const saved = await page.request.get(`${API}/api/v1/auth/me/preferences`);
    const document = (await saved.json()) as Record<string, unknown>;
    expect(JSON.stringify(document)).not.toContain(SENTINEL_KEY);
  } finally {
    await fake.close();
  }
});
