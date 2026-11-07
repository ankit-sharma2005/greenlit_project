import { expect, test } from "@playwright/test";

import { WEB, register } from "./helpers";

/**
 * What a refused request looks like to the person, in the real wizard.
 *
 * The server is backend/tests/support/refusal_server.py, started by
 * scripts/run-e2e.sh on E2E_REFUSAL_PORT (9503) and addressed by mode path, so
 * every case here is a real HTTP answer the API has to diagnose — never a stub
 * inside the page.
 *
 * The bug this covers: every HTML 401/403 was reported as "an anti-bot or CSRF
 * challenge", while a CDN that blocks automation was reported as an expired
 * session. Here each answer must reach the screen as the code it was named.
 */
const REFUSALS = process.env.E2E_REFUSAL_URL ?? "http://127.0.0.1:9503";

/** A cookie and a CSRF token in the pasted cURL: neither may ever be shown. */
const SENTINEL = "sentinel-refusal-secret";

const CASES = [
  {
    mode: "nginx_forbidden",
    kind: "auth_error",
    // A plain 403 from a web server, sent with a session: not a challenge.
    says: "with the pasted session",
  },
  {
    mode: "csrf_json",
    kind: "csrf_rejected",
    says: "fresh cURL",
  },
  {
    mode: "cloudflare_challenge",
    kind: "blocked_by_site",
    says: "Cloudflare",
  },
  {
    mode: "rate_limited",
    kind: "http_error",
    says: "rate-limiting",
  },
] as const;

function curlFor(mode: string): string {
  return [
    `curl -X POST ${REFUSALS}/${mode}`,
    '-H "Content-Type: application/json"',
    `-H "Cookie: session=${SENTINEL}"`,
    `-H "X-CSRFToken: ${SENTINEL}"`,
    `-d '{"question":"hello"}'`,
  ].join(" ");
}

for (const item of CASES) {
  test(`the wizard names a ${item.mode} refusal and shows no secret`, async ({
    page,
    request,
  }) => {
    test.setTimeout(150_000);
    await register(
      page,
      `Refusal ${item.mode}`,
      `refusal-${item.mode}-${Date.now()}@example.com`,
    );

    await page.goto(`${WEB}/`);
    await expect(page.getByTestId("connector-select")).toBeVisible({ timeout: 20_000 });
    await page.getByRole("button", { name: "Website chatbot (wizard)" }).click();
    await page.getByTestId("permission-confirmed").check();
    await page
      .getByTestId("permission-reference")
      .fill("local refusal server, run by this test");
    await page.getByLabel("This app runs on my computer").check();

    const curlInput = page.getByTestId("website-curl");
    await curlInput.fill(curlFor(item.mode));
    await page.getByTestId("website-message").fill("hello");
    await page.getByTestId("website-read").click();

    // The person reads why this was refused, in plain words.
    await expect(page.getByTestId("check-refusal-summary")).toContainText(item.says, {
      timeout: 45_000,
    });
    await expect(page.getByTestId("check-refusal-kind")).toContainText(item.kind);
    await expect(page.getByTestId("check-refusal-evidence")).toBeVisible();
    await expect(page.getByTestId("check-refusal-headers")).toBeVisible();

    // The session cookie and CSRF token were sent: neither may be echoed back.
    const shown = await page.locator("body").innerText();
    expect(shown).not.toContain(SENTINEL);
    await expect(curlInput).toHaveValue("");

    // Exactly one request: retrying a challenge is what gets a runner blocked.
    const counts = await request.get(`${REFUSALS}/_calls`);
    expect(counts.status()).toBe(200);
    const seen = (await counts.json()) as Record<string, number>;
    expect(seen[item.mode]).toBe(1);
  });
}
