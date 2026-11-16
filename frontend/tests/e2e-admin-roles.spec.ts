import { test, expect, request } from "@playwright/test";

import { API, ADMIN_EMAIL, PASSWORD, WEB, ensureAdmin, login } from "./helpers";

/**
 * An admin changes a member's role in Settings -> Users and roles, and the
 * member's own view changes after a reload.
 *
 * A fresh stack makes the first account the admin, so `ensureAdmin` seeds
 * admin@example.com (the account e2e-admin.spec.ts also uses) and the member is
 * registered through the public form. Calibration is the reviewer-or-admin page:
 * the member is refused there with the server's exact sentence plus the hint,
 * and once promoted to reviewer the same page loads without either.
 */
const SCREENS = "../local-prompts/screens";

test("an admin promotes a member, and the member loses the role refusal", async ({
  page,
  browser,
}) => {
  test.setTimeout(180_000);
  await ensureAdmin();

  const memberEmail = `roles-member${Date.now()}@example.com`;
  const api = await request.newContext({ baseURL: API });
  try {
    const created = await api.post("/api/v1/auth/register", {
      data: { email: memberEmail, name: "Role Member", password: PASSWORD },
    });
    expect(created.status()).toBe(201);
  } finally {
    await api.dispose();
  }

  // The member's own browser, before the change.
  const memberContext = await browser.newContext();
  const memberPage = await memberContext.newPage();
  await login(memberPage, memberEmail);

  await memberPage.goto(`${WEB}/settings`);
  await expect(memberPage.getByTestId("settings-tab-demo-apps")).toBeVisible();
  await expect(memberPage.getByTestId("settings-tab-users-and-roles")).toHaveCount(0);

  await memberPage.goto(`${WEB}/calibration`);
  await expect(memberPage.getByTestId("calibration-error")).toContainText(
    "Your role does not allow this action.",
  );
  await expect(memberPage.getByTestId("calibration-role-hint")).toContainText(
    "This needs the reviewer or admin role.",
  );

  // The admin promotes the member in the Users and roles section.
  await login(page, ADMIN_EMAIL);
  await page.goto(`${WEB}/settings`);
  await page.getByTestId("settings-tab-users-and-roles").click();
  await page.getByTestId("users-search").fill(memberEmail);
  await expect(page.getByTestId(`users-role-${memberEmail}`)).toHaveText("member");
  await page.getByTestId(`users-select-${memberEmail}`).selectOption("reviewer");
  await expect(page.getByTestId("users-roles-confirm")).toContainText(memberEmail);
  await expect(page.getByTestId("users-roles-confirm")).toContainText("reviewer");
  await page.getByTestId("users-roles-confirm").getByRole("button", { name: "Change role" }).click();
  await expect(page.getByTestId("users-roles-notice")).toContainText("reviewer");

  await page.setViewportSize({ width: 1280, height: 900 });
  await page.screenshot({ path: `${SCREENS}/users-roles-1280-dark.png`, fullPage: true });
  await page.evaluate(() => {
    document.documentElement.dataset.theme = "light";
  });
  await page.screenshot({ path: `${SCREENS}/users-roles-1280-light.png`, fullPage: true });
  await page.setViewportSize({ width: 375, height: 800 });
  await page.screenshot({ path: `${SCREENS}/users-roles-375.png`, fullPage: true });

  // The member reloads Calibration: the refusal and its hint are gone.
  await memberPage.goto(`${WEB}/calibration`);
  await expect(memberPage.getByTestId("calibration-error")).toHaveCount(0);
  await expect(memberPage.getByTestId("calibration-role-hint")).toHaveCount(0);
  await expect(memberPage.getByTestId("calibration-loading")).toHaveCount(0);

  // The role is visible in the top bar, and the member still cannot see the
  // admin-only section.
  await memberPage.goto(`${WEB}/settings`);
  await expect(memberPage.getByTestId("settings-tab-users-and-roles")).toHaveCount(0);
  await expect(memberPage.getByTestId("user-role")).toContainText("reviewer");

  await memberContext.close();
});
