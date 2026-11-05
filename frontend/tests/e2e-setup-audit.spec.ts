import { test, expect } from "@playwright/test";

import {
  ADMIN_EMAIL,
  API,
  GOLDEN_CSV,
  WEB,
  ensureAdmin,
  login,
  uploadApprovedDataset,
} from "./helpers";

/**
 * Setup checklist and the audit screen (spec 8.4).
 *
 * Both are "real status" surfaces: the checklist reflects shared providers and
 * the current owner's approved datasets, while the audit table reads the
 * append-only log through its server-side filter.
 */
test("the setup checklist tracks real state and the audit tab lists real events", async ({
  page,
}) => {
  await ensureAdmin();
  await login(page, ADMIN_EMAIL);

  await page.goto(`${WEB}/`);
  const checklist = page.getByTestId("setup-checklist");
  await expect(checklist).toBeVisible();
  const providersResponse = await page.request.get(`${API}/api/v1/providers`);
  expect(providersResponse.status()).toBe(200);
  const providers = (await providersResponse.json()) as unknown[];
  const providerStep = page.getByTestId("setup-provider");
  await expect(providerStep).toHaveAttribute("data-done", String(providers.length > 0));

  // Approve a dataset and verify the checklist reflects it.
  await uploadApprovedDataset(page, `Setup golden ${Date.now()}`, GOLDEN_CSV);
  await page.reload();
  await expect(page.getByTestId("setup-dataset")).toHaveAttribute("data-done", "true");

  // Settings -> Audit log is a real, admin-only table, not a placeholder.
  await page.click("text=Settings");
  await page.waitForURL(/.*\/settings/);
  await page.getByRole("button", { name: "Audit log" }).click();
  await expect(page.getByTestId("audit-table")).toBeVisible();
  await expect(page.getByTestId("audit-table")).toContainText("auth.register");
  await expect(page.getByTestId("audit-range")).toContainText("of");

  // The filter runs on the server: an action that never happened is empty.
  await page.fill('[data-testid="audit-action-filter"]', "role_changed");
  await expect(page.getByTestId("audit-empty")).toBeVisible();

  await page.fill('[data-testid="audit-action-filter"]', "auth");
  await expect(page.getByTestId("audit-table")).toContainText("auth.register");
  await expect(page.getByTestId("audit-empty")).toHaveCount(0);

  // Settings -> Safety is a real, read-only catalogue of what a run sends.
  await page.getByTestId("settings-tab-safety").click();
  await expect(page.getByTestId("safety-panel")).toBeVisible();
  await expect(page.getByTestId("safety-summary-attacks")).toHaveText("44");
  await expect(page.getByTestId("safety-summary-safe")).toHaveText("26");
  await expect(page.getByTestId("safety-summary-version")).toHaveText("1.0");
  await expect(page.getByTestId("safety-verdict-note")).toContainText("hard NO-GO");
  await expect(page.getByTestId("safety-verdict-note")).toContainText("synthetic test marker");
  await expect(page.getByTestId("safety-readonly-note")).toContainText("not supported yet");

  // A category button filters the item list; the search narrows it further.
  await expect(page.getByTestId("safety-item-list").getByRole("row")).toHaveCount(45);
  await page.getByTestId("safety-category-system_prompt_leak").click();
  await expect(page.getByTestId("safety-item-list").getByRole("row")).toHaveCount(9);
  await page.getByTestId("safety-search").fill("sl-01");
  await expect(page.getByTestId("safety-item-list").getByRole("row")).toHaveCount(2);

  // Settings -> Criteria explains the engine's real thresholds and rules.
  await page.getByTestId("settings-tab-criteria").click();
  await expect(page.getByTestId("criteria-panel")).toBeVisible();
  await expect(page.getByTestId("criteria-thresholds")).toContainText("below 0.60");
  await expect(page.getByTestId("criteria-thresholds")).toContainText("0.60–0.80");
  await expect(page.getByTestId("criteria-thresholds")).toContainText("from 0.80");
  await expect(page.getByTestId("criteria-metric-answer_match")).toContainText("0.40");
  await expect(page.getByTestId("criteria-metric-output_nonempty")).toContainText("hard gate");
  await expect(page.getByTestId("criteria-metric-attack_resisted")).toContainText("hard gate");
  await expect(page.getByTestId("criteria-rules").getByRole("listitem")).toHaveCount(5);
  await expect(page.getByTestId("criteria-readonly-note")).toContainText(
    "Editing criteria is not supported yet",
  );
  await expect(page.getByTestId("settings-tab-criteria")).not.toContainText("soon");

  // Account and Preferences are real now; only Connectors still says "soon".
  await expect(page.getByTestId("settings-tab-connectors")).toContainText("soon");
  await expect(page.getByTestId("settings-tab-account")).not.toContainText("soon");
  await expect(page.getByTestId("settings-tab-preferences")).not.toContainText("soon");

  // Account shows the signed-in user's own record, never an invented one.
  await page.getByTestId("settings-tab-account").click();
  await expect(page.getByTestId("account-panel")).toBeVisible();
  await expect(page.getByTestId("account-email")).toHaveText(ADMIN_EMAIL);
  await expect(page.getByTestId("account-role")).toHaveText("admin");
  await expect(page.getByTestId("account-active")).toHaveText("Active");
  await expect(page.getByTestId("account-created")).not.toHaveText("Unknown");

  // A display-name change is stored on the account and survives a reload.
  await page.getByTestId("account-name").fill("Setup Admin");
  await page.getByTestId("account-save").click();
  await expect(page.getByTestId("account-notice")).toContainText("Display name saved.");
  await page.reload();
  await page.getByTestId("settings-tab-account").click();
  await expect(page.getByTestId("account-name")).toHaveValue("Setup Admin");

  // Preferences apply at once, save to the account, and are restored from the
  // API after a reload — even with the local cache removed first.
  await page.getByTestId("settings-tab-preferences").click();
  await expect(page.getByTestId("preferences-panel")).toBeVisible();
  await page.getByTestId("theme-light").check();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(page.getByTestId("preferences-notice")).toContainText("Appearance saved.");
  await page.evaluate(() => window.localStorage.removeItem("greenlit-theme"));
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");

  // Put the account back the way the rest of the suite expects it.
  await page.getByTestId("settings-tab-preferences").click();
  await page.getByTestId("theme-dark").check();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByTestId("settings-tab-account").click();
  await page.getByTestId("account-name").fill("Admin");
  await page.getByTestId("account-save").click();
  await expect(page.getByTestId("account-name-value")).toHaveText("Admin");
});
