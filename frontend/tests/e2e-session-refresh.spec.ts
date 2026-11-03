import { test, expect } from "@playwright/test";

import { WEB, register } from "./helpers";

test.describe("session refresh", () => {
  test("keeps the user signed in after the access cookie expires and refreshes once", async ({
    page,
    context,
  }) => {
    const email = `session-refresh-${Date.now()}@example.com`;
    await register(page, "Session User", email);

    // Confirm we're signed in by hitting a protected page.
    await page.goto(`${WEB}/`);
    await expect(page.getByText(/GreenLit/i).first()).toBeVisible({ timeout: 15_000 });

    // Expire only the access token: the refresh cookie should silently renew the session.
    await context.clearCookies({ name: "greenlit_access" });

    // Trigger an authenticated request; api.ts should refresh once and retry.
    await page.reload();
    await expect(page).not.toHaveURL(/\/login/);
    await expect(page.getByText(/GreenLit/i).first()).toBeVisible({ timeout: 15_000 });

    // A second reload after the refresh should still work (cookie replaced).
    await page.reload();
    await expect(page).not.toHaveURL(/\/login/);
  });

  test("lands on /login with the session-expired sentence when both cookies are gone", async ({
    page,
    context,
  }) => {
    const email = `session-expired-${Date.now()}@example.com`;
    await register(page, "Expired User", email);

    await page.goto(`${WEB}/`);
    await expect(page).not.toHaveURL(/\/login/);

    // Remove both cookies: refresh cannot recover the session.
    await context.clearCookies({ name: "greenlit_access" });
    await context.clearCookies({ name: "greenlit_refresh" });

    await page.reload();

    await expect(page).toHaveURL(/\/login/);
    // The app tells the user the session expired and to sign in again.
    await expect(page.getByText(/session expired/i)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/sign in again/i)).toBeVisible({ timeout: 10_000 });
  });
});
