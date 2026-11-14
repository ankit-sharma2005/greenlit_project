/**
 * Settings → Preferences: the defaults a new test opens with.
 *
 * They belong to the account, so a reload reads them back from the server, and
 * New Test is pre-filled from them without replacing anything already typed.
 */

import { expect, test } from "@playwright/test";

import { WEB, register } from "./helpers";

test("saved preferences survive a reload and pre-fill a new test", async ({ page }) => {
  await register(page, "Prefs User", `prefs-${Date.now()}@example.com`);

  await page.goto(`${WEB}/settings`);
  await page.getByTestId("settings-tab-preferences").click();
  await expect(page.getByTestId("preferences-panel")).toBeVisible();

  await page.selectOption('[data-testid="preferences-entry-point"]', "prompt_app");
  await expect(page.getByTestId("preferences-notice")).toHaveText("Default entry point saved.");

  // Only quality. A new account has no stored test types, so the boxes must be
  // set explicitly; each save disables the controls, so wait before the next one.
  const quality = page.getByTestId("preferences-test-type-quality");
  await expect(quality).toBeEnabled();
  await quality.check();
  await expect(page.getByTestId("preferences-notice")).toHaveText("Default test types saved.");
  for (const type of ["safety", "operations"]) {
    const box = page.getByTestId(`preferences-test-type-${type}`);
    await expect(box).toBeEnabled();
    if (await box.isChecked()) await box.uncheck();
  }
  await expect(page.getByTestId("preferences-test-type-quality")).toBeChecked();
  await expect(page.getByTestId("preferences-test-type-safety")).not.toBeChecked();

  await page.reload();
  await page.getByTestId("settings-tab-preferences").click();
  await expect(page.getByTestId("preferences-entry-point")).toHaveValue("prompt_app");
  await expect(page.getByTestId("preferences-test-type-quality")).toBeChecked();
  await expect(page.getByTestId("preferences-test-type-safety")).not.toBeChecked();
  await expect(page.getByTestId("preferences-test-type-operations")).not.toBeChecked();

  // A new test opens on the saved form, with the saved test types.
  await page.goto(`${WEB}/`);
  await expect(page.getByTestId("connector-select")).toHaveValue("prompt_app");
  await expect(page.getByLabel("Quality", { exact: true })).toBeChecked();
  await expect(page.getByLabel("Safety", { exact: true })).not.toBeChecked();
  await expect(page.getByLabel(/Operations/)).not.toBeChecked();
});
