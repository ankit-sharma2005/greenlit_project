/**
 * Two devices signed in to one account, proved in a real browser.
 *
 * The second browser context is a real second device: its own cookie jar, its own
 * login, its own refresh-token family. Settings → Account marks the browser that
 * is looking as "This device", signing the other one out leaves this one in, and
 * the other one is signed out on its very next request. Neither surface shows a
 * token, a hash or a family id.
 */

import path from "node:path";

import { expect, test } from "@playwright/test";

import { API, WEB, login, register } from "./helpers";

const SCREENS = path.resolve(process.cwd(), "..", "local-prompts", "screens");

test("a second device is listed, signed out from here, and signed out on its next request", async ({
  page,
  browser,
}) => {
  test.setTimeout(180_000);
  const email = `sessions-${Date.now()}@example.com`;
  await register(page, "Sessions User", email);

  const other = await browser.newContext();
  const otherPage = await other.newPage();
  try {
    // The second device: a separate cookie jar, so a separate session family.
    await login(otherPage, email);

    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(`${WEB}/settings`);
    await page.getByTestId("settings-tab-account").click();
    await expect(page.getByTestId("account-sessions")).toBeVisible();

    // Both devices are listed, and exactly one of them is the browser looking.
    await expect(page.getByTestId("session-row")).toHaveCount(2, { timeout: 20_000 });
    await expect(page.getByTestId("session-current")).toHaveCount(1);
    await expect(page.getByTestId("session-current")).toHaveText("This device");

    await page.screenshot({ path: path.join(SCREENS, "after-sessions-two-devices-1280x900.png") });

    // What the API sends is a device label and two times, never a token or a hash.
    const listed = await page.request.get(`${API}/api/v1/auth/sessions`);
    expect(listed.status(), await listed.text()).toBe(200);
    const payload = await listed.text();
    expect(payload).not.toMatch(/token|hash|refresh/i);
    expect(payload).not.toMatch(/\b[0-9a-f]{32,}\b/i);
    const sessionText = await page.getByTestId("account-sessions").innerText();
    expect(sessionText).not.toMatch(/token|hash/i);
    expect(sessionText).not.toMatch(/\b[0-9a-f]{32,}\b/i);

    // Sign the other device out from this one, after the confirmation.
    await page.getByTestId("session-revoke-others").click();
    await expect(page.getByTestId("session-confirm")).toContainText("This device stays signed in");
    await page.getByTestId("session-revoke-others-confirm").click();
    await expect(page.getByTestId("sessions-notice")).toHaveText("Signed out 1 other device.");
    await expect(page.getByTestId("session-row")).toHaveCount(1, { timeout: 20_000 });
    await expect(page.getByTestId("session-current")).toHaveCount(1);

    // The revoked device is out on its next request, not on its next sign-in.
    const revoked = await otherPage.request.get(`${API}/api/v1/auth/me`);
    expect(revoked.status(), await revoked.text()).toBe(401);
    await otherPage.reload();
    await expect(otherPage).toHaveURL(/\/login/, { timeout: 20_000 });

    // This device is still in.
    await page.reload();
    await expect(page).not.toHaveURL(/\/login/);
    await page.getByTestId("settings-tab-account").click();
    await expect(page.getByTestId("session-current")).toHaveText("This device");

    await page.setViewportSize({ width: 375, height: 800 });
    const overflow = await page.evaluate(() => {
      const documentElement = document.documentElement;
      const main = document.querySelector("main.page");
      if (!main) throw new Error("main.page is missing");
      return {
        horizontal: documentElement.scrollWidth > documentElement.clientWidth,
        mainOverflowY: getComputedStyle(main).overflowY,
      };
    });
    expect(overflow.horizontal).toBe(false);
    expect(overflow.mainOverflowY).toBe("auto");
    await page.screenshot({ path: path.join(SCREENS, "after-sessions-remaining-375x800.png") });
  } finally {
    await other.close();
  }
});
