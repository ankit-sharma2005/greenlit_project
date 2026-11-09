/**
 * The analyst's successful path, in a real browser and both themes.
 *
 * A local target answers the golden questions correctly; the fake analyst replies with plain
 * prose. The panel must show the preview, explain on one click (no remote confirmation, because
 * the provider is on loopback), render the answer under the "AI explanation" label with the
 * provider and model named, and leave the verdict and metrics untouched.
 */

import path from "node:path";

import { expect, test } from "@playwright/test";

import {
  API,
  GOLDEN_ANSWERS,
  GOLDEN_CSV,
  WEB,
  createProvider,
  register,
  startApp,
  startFakeProvider,
} from "./helpers";

const SCREENS = path.resolve(process.cwd(), "..", "local-prompts", "screens");
const REPLY = "Answer match sits below its threshold, so read the first failed case first.";

async function finished(page: import("@playwright/test").Page, runId: string): Promise<void> {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const response = await page.request.get(`${API}/api/v1/runs/${runId}`);
    const run = (await response.json()) as { state: string };
    if (["completed", "failed", "cancelled"].includes(run.state)) {
      expect(run.state, "the plain run must complete").toBe("completed");
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error(`Run ${runId} did not finish in two minutes.`);
}

test("Explain this run shows an answer in plain text and changes no verdict", async ({ page }) => {
  test.setTimeout(240_000);
  const target = await startApp((data) => {
    const question = typeof data.question === "string" ? data.question : "";
    return {
      answer: GOLDEN_ANSWERS[question] ?? "I am not sure about that.",
      context: `${GOLDEN_ANSWERS[question] ?? ""} (handbook)`,
    };
  });
  const fake = await startFakeProvider({ analystReply: REPLY });
  try {
    await register(page, "Analyst Success", `analystok${Date.now()}@example.com`);

    const providerId = await createProvider(page, {
      name: `Analyst success provider ${Date.now()}`,
      model: "llama3",
      baseUrl: `http://127.0.0.1:${fake.port}/v1`,
    });
    const preferences = await page.request.patch(`${API}/api/v1/auth/me/preferences`, {
      data: { theme: "dark", analyst: { provider_id: providerId, model: "llama3" } },
    });
    expect(preferences.status(), await preferences.text()).toBe(200);

    const dataset = await page.request.post(`${API}/api/v1/datasets`, {
      multipart: {
        name: `Analyst success dataset ${Date.now()}`,
        file: { name: "golden.csv", mimeType: "text/csv", buffer: Buffer.from(GOLDEN_CSV) },
      },
    });
    expect(dataset.status(), await dataset.text()).toBe(201);
    const datasetId = ((await dataset.json()) as { id: string }).id;
    const approved = await page.request.post(
      `${API}/api/v1/datasets/${datasetId}/versions/1/approve`,
    );
    expect(approved.status(), await approved.text()).toBe(200);
    const versions = await page.request.get(`${API}/api/v1/datasets/${datasetId}/versions`);
    const versionList = (await versions.json()) as Array<{ id: string; version_no: number }>;
    const version = versionList.find((entry) => entry.version_no === 1);
    expect(version).toBeTruthy();

    const created = await page.request.post(`${API}/api/v1/runs`, {
      data: {
        name: "Explained run",
        entry_point: "http_endpoint",
        target: `http://127.0.0.1:${target.port}/chat`,
        body_template: '{"question": {{input}}}',
        answer_path: "answer",
        context_path: "context",
        timeout_seconds: 60,
        allow_private_targets: true,
        dataset_version_id: version!.id,
      },
    });
    expect(created.status(), await created.text()).toBe(202);
    const runId = ((await created.json()) as { id: string }).id;
    await finished(page, runId);
    const before = await (await page.request.get(`${API}/api/v1/runs/${runId}`)).json();

    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(`${WEB}/results`);
    await page.getByTestId("run-history-open").first().click();

    const panel = page.getByTestId("analyst-panel");
    await expect(panel).toBeVisible();
    await expect(page.getByTestId("analyst-preview-input")).toContainText("METRICS");
    // Loopback provider: local, so no remote confirmation is asked for.
    await expect(page.getByTestId("analyst-confirm-remote")).toHaveCount(0);
    await expect(page.getByTestId("analyst-provider-note")).toContainText("local");

    await page.getByTestId("analyst-explain").click();

    const explanation = page.getByTestId("analyst-explanation");
    await expect(explanation).toBeVisible({ timeout: 60_000 });
    await expect(explanation).toContainText(
      "AI explanation. It may be wrong and does not affect the verdict.",
    );
    await expect(page.getByTestId("analyst-text")).toHaveText(REPLY);
    await expect(page.getByTestId("analyst-model")).toContainText("analyst-v1");
    await expect(page.getByTestId("analyst-model")).toContainText("llama3");
    // Plain text only: the panel created no image and no link from the model's words.
    await expect(panel.locator("img")).toHaveCount(0);
    await expect(panel.locator("a")).toHaveCount(0);

    await page.screenshot({ path: path.join(SCREENS, "after-analyst-1280x900-dark.png") });

    await page.evaluate(() => document.documentElement.setAttribute("data-theme", "light"));
    await expect(explanation).toBeVisible();
    await page.screenshot({ path: path.join(SCREENS, "after-analyst-1280x900-light.png") });
    await page.evaluate(() => document.documentElement.setAttribute("data-theme", "dark"));

    const after = await (await page.request.get(`${API}/api/v1/runs/${runId}`)).json();
    expect(after.verdict).toBe(before.verdict);
    expect(after.score).toBe(before.score);
    expect(JSON.stringify(after.metrics)).toBe(JSON.stringify(before.metrics));

    // A second click reuses the stored row: the same text, still one explanation.
    await page.getByTestId("analyst-explain").click();
    await expect(page.getByTestId("analyst-text")).toHaveText(REPLY);
  } finally {
    await fake.close();
    await target.close();
  }
});
