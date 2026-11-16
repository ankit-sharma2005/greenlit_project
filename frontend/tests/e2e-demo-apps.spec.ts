import { test, expect } from "@playwright/test";

import { API, WEB, register } from "./helpers";

/**
 * The Demo apps tab against the e2e stand-ins.
 *
 * The real catalog ports (9111 to 9115) are not reachable from this stack, so
 * `scripts/run-e2e.sh` starts two stand-ins and exports the test-only probe
 * override; the backend reads it once at startup. support-bot is on :9505 with a
 * health-only server, math-solver is on :9506 with the deterministic app the
 * regression spec uses, and the other six keep their real (down) addresses.
 */
const SCREENS = "../local-prompts/screens";

test("the catalog shows what is up, connects one target and keeps the warning", async ({
  page,
}) => {
  test.setTimeout(180_000);
  await register(page, "Demo User", `demo-apps${Date.now()}@example.com`);

  await page.goto(`${WEB}/settings`);
  await page.getByTestId("settings-tab-demo-apps").click();

  // Up comes from the stand-ins, down from the real catalog addresses that are
  // not reachable from this stack.
  await expect(page.getByTestId("demo-status-support-bot")).toHaveText("running");
  await expect(page.getByTestId("demo-mode-support-bot")).toContainText("guarded");
  await expect(page.getByTestId("demo-status-math-solver")).toHaveText("running");
  await expect(page.getByTestId("demo-mode-math-solver")).toContainText("Mode: correct");
  for (const down of ["docs-rag", "stream-bot", "tool-agent"]) {
    await expect(page.getByTestId(`demo-status-${down}`)).toHaveText("not running");
    await expect(page.getByTestId(`demo-mode-${down}`)).toContainText("not reported");
  }
  for (const down of ["reliability-lab", "vault-bot", "site-bot"]) {
    await expect(page.getByTestId(`demo-status-${down}`)).toHaveText("not running");
  }
  await expect(page.getByTestId(/^demo-card-/)).toHaveCount(8);
  await expect(page.getByTestId("demo-apps-warning")).toContainText("never be exposed");

  await page.setViewportSize({ width: 1280, height: 900 });
  await page.screenshot({ path: `${SCREENS}/demo-apps-1280-dark.png`, fullPage: true });
  await page.getByTestId("settings-tab-demo-apps").click();
  await page.evaluate(() => {
    document.documentElement.dataset.theme = "light";
  });
  await page.screenshot({ path: `${SCREENS}/demo-apps-1280-light.png`, fullPage: true });
  await page.setViewportSize({ width: 375, height: 800 });
  await page.screenshot({ path: `${SCREENS}/demo-apps-375.png`, fullPage: true });
  await page.setViewportSize({ width: 1280, height: 900 });

  // Connect asks for a confirmation that repeats the local-only warning.
  await page.getByTestId("demo-connect-support-bot").click();
  await expect(page.getByTestId("demo-confirm-support-bot")).toContainText(
    "never expose it to the internet",
  );
  await page.getByTestId("demo-confirm-yes-support-bot").click();
  await expect(page.getByTestId("demo-open-support-bot")).toBeVisible();
  await expect(page.getByTestId("demo-smoke-support-bot")).toBeVisible();

  // Exactly one saved target, and a second connect call does not duplicate it.
  const listed = await page.request.get(`${API}/api/v1/saved-targets`);
  const before = (await listed.json()) as { items: Array<{ id: string; name: string }> };
  const mine = before.items.filter((item) => item.name === "Acme support bot");
  expect(mine).toHaveLength(1);
  expect(mine[0].id).toBeTruthy();
  const again = await page.request.post(`${API}/api/v1/demo-apps/support-bot/connect`);
  expect(again.status(), await again.text()).toBe(201);
  const after = (await (await page.request.get(`${API}/api/v1/saved-targets`)).json()) as {
    total: number;
  };
  expect(after.total).toBe(1);

  // The smoke-test link opens New Test with this app's own fields filled in.
  await page.getByTestId("demo-smoke-support-bot").click();
  await expect(page).toHaveURL(/\/\?demo_app=support-bot/);
  await expect(page.getByTestId("target-url")).toHaveValue("http://host.docker.internal:9111/");
});
