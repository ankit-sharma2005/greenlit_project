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
});
