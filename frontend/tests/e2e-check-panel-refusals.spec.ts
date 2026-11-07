import { expect, test } from "@playwright/test";

import { WEB, register } from "./helpers";

/**
 * The same four refusals, through the check panel instead of the wizard.
 *
 * The panel is only offered for a target that is not "on my computer", so this
 * spec reaches the harness's refusal server through the host's own name. The
 * server answers the very first request with a readable 200 (the panel appears
 * only after a successful first contact) and every request after it with the
 * real refusal — the four shapes are the ones `refusal_server.py` serves and the
 * backend tests assert.
 */
const REFUSALS = process.env.E2E_REFUSAL_CHECK_URL ?? "http://host.docker.internal:9503";

/** A cookie and a CSRF token in the pasted cURL: neither may ever be shown. */
const SENTINEL = "sentinel-check-panel-secret";

const CASES = [
  { mode: "nginx_forbidden", kind: "auth_error", says: "with the pasted session" },
  { mode: "csrf_json", kind: "csrf_rejected", says: "fresh cURL" },
  { mode: "cloudflare_challenge", kind: "blocked_by_site", says: "Cloudflare" },
  { mode: "rate_limited", kind: "http_error", says: "rate-limiting" },
] as const;

function curlFor(mode: string): string {
  return [
    `curl -X POST ${REFUSALS}/first-ok/${mode}`,
    '-H "Content-Type: application/json"',
    `-H "Cookie: session=${SENTINEL}"`,
    `-H "X-CSRFToken: ${SENTINEL}"`,
    `-d '{"question":"hello"}'`,
  ].join(" ");
}

for (const item of CASES) {
  test(`the check panel names a ${item.mode} refusal and shows no secret`, async ({
    page,
    request,
  }) => {
    test.setTimeout(180_000);
    await register(
      page,
      `Check panel ${item.mode}`,
      `check-panel-${item.mode}-${Date.now()}@example.com`,
    );

    const calls = async (): Promise<number> => {
      const response = await request.get(`${REFUSALS}/_calls`);
      expect(response.status()).toBe(200);
      const seen = (await response.json()) as Record<string, number>;
      return seen[item.mode] ?? 0;
    };

    await page.goto(`${WEB}/`);
    await expect(page.getByTestId("connector-select")).toBeVisible({ timeout: 20_000 });

    // A pasted cURL carries the session: the same import the product uses.
    await page.getByRole("button", { name: "Paste cURL" }).click();
    await page.fill("#curl-input", curlFor(item.mode));
    await page.getByRole("button", { name: "Use this request" }).click();
    await expect(page.getByTestId("target-url")).toHaveValue(`${REFUSALS}/first-ok/${item.mode}`);

    // Not "on my computer": that is when the panel is the first-contact step.
    await page.getByTestId("permission-confirmed").check();
    await page
      .getByTestId("permission-reference")
      .fill("local refusal server, run by this test");
    await page.getByTestId("start-test").click();

    // First contact succeeds, so the panel is offered and a run stays blocked.
    await expect(page.getByTestId("detect-result")).toBeVisible({ timeout: 90_000 });
    await expect(page.getByTestId("target-check-panel")).toBeVisible();
    await expect(page.getByTestId("run-full")).toBeDisabled();

    const before = await calls();
    await page.getByTestId("target-check-button").click();

    await expect(page.getByTestId("check-refusal-summary")).toContainText(item.says, {
      timeout: 60_000,
    });
    await expect(page.getByTestId("check-refusal-kind")).toContainText(item.kind);
    await expect(page.getByTestId("check-refusal-evidence")).toBeVisible();
    await expect(page.getByTestId("check-refusal-headers")).toBeVisible();

    // The cookie and the CSRF token were sent: neither may be echoed back.
    const shown = await page.locator("body").innerText();
    expect(shown).not.toContain(SENTINEL);

    // A refused check accepts nothing, so no run may start.
    await expect(page.getByTestId("run-full")).toBeDisabled();
    await expect(page.getByTestId("run-full-blocked")).toBeVisible();

    // Exactly one request for the check itself (the counter is on the server).
    expect(await calls()).toBe(before + 1);
  });
}
