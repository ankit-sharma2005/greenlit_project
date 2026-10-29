import { test, expect } from "@playwright/test";

import { WEB, register } from "./helpers";

/**
 * One click on "Try the demo" must produce a GO for the healthy helpdesk app and
 * a NO-GO for the broken one, with the reason spelled out.
 *
 * Both runs go through the normal runs API against the demo servers that
 * `scripts/run-e2e.sh` starts, so nothing here is precomputed.
 */
test("try the demo shows a GO for the healthy app and a NO-GO for the broken one", async ({
  page,
}) => {
  test.setTimeout(240_000);

  await register(page, "Demo Viewer", `demo${Date.now()}@example.com`);
  await page.goto(`${WEB}/`);
  await expect(page.getByTestId("try-demo")).toBeVisible({ timeout: 20_000 });
  await page.click('[data-testid="try-demo"]');

  // The healthy app: a perfect score and a GO.
  await expect(page.getByTestId("demo-good-verdict")).toHaveText("Go", { timeout: 180_000 });
  await expect(page.getByTestId("demo-good-score")).toHaveText("1.00");
  await expect(page.getByTestId("demo-good-reason")).toContainText("GO threshold 0.80");
  await expect(page.getByTestId("demo-error")).toHaveCount(0);

  // The broken app: NO-GO, and the reason names the weighted score and the
  // REVIEW threshold, not just "it failed".
  await expect(page.getByTestId("demo-broken-verdict")).toHaveText("No-Go", { timeout: 180_000 });
  await expect(page.getByTestId("demo-broken-reason")).toContainText("Weighted score");
  await expect(page.getByTestId("demo-broken-reason")).toContainText("REVIEW threshold 0.60");
  await expect(page.getByTestId("demo-broken-score")).not.toHaveText("1.00");
});
