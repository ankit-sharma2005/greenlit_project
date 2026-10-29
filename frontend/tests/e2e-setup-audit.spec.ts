import { test, expect } from "@playwright/test";

import { GOLDEN_CSV, WEB, register, uploadApprovedDataset } from "./helpers";

/**
 * Setup checklist and the audit screen (spec 8.4).
 *
 * Both are "real status" surfaces: the checklist counts what actually exists, and
 * the audit table reads the append-only log through its server-side filter. The
 * test walks the first-run path with no provider and no dataset, then approves a
 * dataset and checks the checklist notices.
 */
test("the setup checklist tracks real state and the audit tab lists real events", async ({
  page,
}) => {
  const email = `setup${Date.now()}@example.com`;
  await register(page, "Setup User", email);

  await page.goto(`${WEB}/`);
  const checklist = page.getByTestId("setup-checklist");
  await expect(checklist).toBeVisible();
  await expect(page.getByTestId("setup-progress")).toHaveText("0 of 3");
  await expect(page.getByTestId("setup-provider-link")).toHaveAttribute("href", "/settings");
  await expect(page.getByTestId("setup-provider")).toHaveAttribute("data-done", "false");
  await expect(page.getByTestId("setup-dataset")).toHaveAttribute("data-done", "false");

  // Approve a dataset: only then does the dataset step count as done.
  await uploadApprovedDataset(page, `Setup golden ${Date.now()}`, GOLDEN_CSV);
  await page.reload();
  await expect(page.getByTestId("setup-progress")).toHaveText("1 of 3");
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
