import { test, expect, type Page } from "@playwright/test";

import { API, WEB, register } from "./helpers";

/**
 * The regression demo with a deterministic stand-in.
 *
 * `scripts/run-e2e.sh` starts it on :9506, the catalog's math-solver probe points
 * at the same origin, and the app flips between correct and faulty through its
 * control endpoint. No model is involved, so a flip is a real change and the
 * noise caution must never appear.
 */
const APP = process.env.E2E_REGRESSION_APP_URL ?? "http://127.0.0.1:9506";
const TARGET = process.env.E2E_REGRESSION_TARGET_URL ?? "http://host.docker.internal:9506/";
const SCREENS = "../local-prompts/screens";

const CSV = [
  "question,answer",
  "What is 12 + 30?,42",
  "What is 7 * 6?,42",
  "What is 100 - 58?,42",
  "What is 90 / 2?,45",
  "What is 2 + 2?,4",
  "What is 10 * 10?,100",
  "",
].join("\n");

async function datasetVersion(page: Page, name: string): Promise<string> {
  const created = await page.request.post(`${API}/api/v1/datasets`, {
    multipart: {
      name,
      file: { name: "sums.csv", mimeType: "text/csv", buffer: Buffer.from(CSV) },
    },
  });
  expect(created.status(), await created.text()).toBe(201);
  const dataset = (await created.json()) as { id: string };
  const approved = await page.request.post(
    `${API}/api/v1/datasets/${dataset.id}/versions/1/approve`,
  );
  expect(approved.status(), await approved.text()).toBe(200);
  const versions = await page.request.get(`${API}/api/v1/datasets/${dataset.id}/versions`);
  const list = (await versions.json()) as Array<{ id: string; version_no: number }>;
  const version = list.find((entry) => entry.version_no === 1);
  expect(version, "version 1 must exist before a run can cite it").toBeTruthy();
  return version!.id;
}

async function startRun(
  page: Page,
  name: string,
  versionId: string,
  criteria = "plain_chatbot",
): Promise<string> {
  // Without this header GreenLit collapses identical settings into the first run,
  // and a regression demo needs two genuinely separate runs.
  const created = await page.request.post(`${API}/api/v1/runs`, {
    headers: { "Idempotency-Key": `${name}-${Date.now()}-${Math.random().toString(16).slice(2)}` },
    data: {
      name,
      entry_point: "http_endpoint",
      target: TARGET,
      body_template: '{"question": {{input}}}',
      answer_path: "answer",
      timeout_seconds: 30,
      allow_private_targets: true,
      dataset_version_id: versionId,
      test_types: ["quality"],
      criteria_profile: criteria,
    },
  });
  expect(created.status(), await created.text()).toBe(202);
  const run = (await created.json()) as { id: string };
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const response = await page.request.get(`${API}/api/v1/runs/${run.id}`);
    const body = (await response.json()) as { state: string };
    if (["completed", "failed", "cancelled"].includes(body.state)) {
      expect(body.state, "the run must finish").toBe("completed");
      return run.id;
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error(`Run ${run.id} did not finish in two minutes.`);
}

async function setMode(mode: "correct" | "faulty"): Promise<void> {
  const response = await fetch(`${APP}/_control/mode`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode }),
  });
  expect(response.status).toBe(200);
}

async function openRun(page: Page, runId: string, name: string): Promise<void> {
  await page.goto(`${WEB}/results`);
  // The list is fetched after the page renders, so wait for this run's own row.
  const row = page.getByTestId("run-history-row").filter({ hasText: name });
  await expect(row.first(), `run ${runId} must be in the history`).toBeVisible();
  await row.first().getByTestId("run-history-open").click();
  await expect(page.getByTestId("run-detail-heading")).toContainText(name);
}

test("a flip on a deterministic target is a regression with flipped cases", async ({ page }) => {
  test.setTimeout(300_000);
  await register(page, "Regression User", `regression${Date.now()}@example.com`);
  await setMode("correct");
  const version = await datasetVersion(page, `Sums ${Date.now()}`);

  // The rag profile scores groundedness, which this dataset cannot measure:
  // that is the metric the compare block must report as "not measured".
  const goodId = await startRun(page, "Sums A", version, "rag_chatbot");
  const pinned = await page.request.post(`${API}/api/v1/runs/${goodId}/baseline`, {
    data: {},
  });
  expect(pinned.status(), await pinned.text()).toBe(201);

  await setMode("faulty");
  const badId = await startRun(page, "Sums B", version, "rag_chatbot");

  await openRun(page, badId, "Sums B");
  await page.getByTestId("compare-toggle").click();
  await expect(page.getByTestId("compare-class-regressed")).toHaveText("Regressed");
  await expect(page.getByTestId("compare-verdict")).toContainText("worse");
  // What flipped is the answer match on every case: 1.00 before, 0.00 now, so
  // all six are listed by the metric that moved (per-case rows need a judge).
  const metricRow = page.getByTestId("compare-metrics").getByRole("row").filter({ hasText: "answer match" });
  await expect(metricRow).toContainText("1.00");
  await expect(metricRow).toContainText("0.00");
  await expect(metricRow).toContainText("-1.00");
  // A metric unmeasured on either side says so, and never shows a delta.
  await expect(page.getByTestId("compare-unmeasured")).toBeVisible();
  await expect(page.getByTestId("compare-metrics")).toContainText("not measured");
  // Deterministic target: no noise caution.
  await expect(page.getByTestId("compare-noise")).toHaveCount(0);

  await page.screenshot({ path: `${SCREENS}/compare-regressed.png`, fullPage: true });

  // A run compared with itself is unchanged.
  const selfCompare = await page.request.get(
    `${API}/api/v1/runs/${goodId}/compare?against=${goodId}`,
  );
  expect(selfCompare.status(), await selfCompare.text()).toBe(200);
  const self = (await selfCompare.json()) as { classification: string; score: { delta: number } };
  expect(self.classification).toBe("unchanged");
  expect(self.score.delta).toBe(0);
});

test("a different criteria profile is not comparable and shows no deltas", async ({ page }) => {
  test.setTimeout(300_000);
  await register(page, "Compare User", `compare${Date.now()}@example.com`);
  await setMode("correct");
  const version = await datasetVersion(page, `Mixed ${Date.now()}`);

  const baselineId = await startRun(page, "Plain profile", version, "rag_chatbot");
  const pinned = await page.request.post(`${API}/api/v1/runs/${baselineId}/baseline`, {
    data: {},
  });
  expect(pinned.status(), await pinned.text()).toBe(201);

  const otherId = await startRun(page, "Other profile", version, "plain_chatbot");

  await openRun(page, otherId, "Other profile");
  await page.getByTestId("compare-toggle").click();
  await expect(page.getByTestId("compare-not-comparable")).toBeVisible();
  await expect(page.getByTestId("compare-reasons")).toContainText("criteria profile");
  await expect(page.getByTestId("compare-metrics")).toHaveCount(0);
  await expect(page.getByTestId("compare-score")).toHaveCount(0);

  await page.screenshot({ path: `${SCREENS}/compare-not-comparable.png`, fullPage: true });
});
