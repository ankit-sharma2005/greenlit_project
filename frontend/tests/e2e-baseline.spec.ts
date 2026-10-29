import { test, expect, type Page } from "@playwright/test";

import { API, WEB, register } from "./helpers";

/** The shipped demo dataset and its two targets, seeded through the demo endpoint. */
interface DemoSetup {
  dataset_id: string;
  dataset_version_id: string;
  good_url: string;
  broken_url: string;
}

async function startDemoRun(page: Page, demo: DemoSetup, url: string, name: string) {
  const created = await page.request.post(`${API}/api/v1/runs`, {
    data: {
      name,
      entry_point: "http_endpoint",
      target: url,
      body_template: '{"question": {{input}}}',
      answer_path: "answer",
      context_path: "context",
      timeout_seconds: 60,
      allow_private_targets: true,
      dataset_version_id: demo.dataset_version_id,
    },
  });
  expect(created.status(), await created.text()).toBe(202);
  const run = (await created.json()) as { id: string };
  await finished(page, run.id);
  return run.id;
}

/** Poll the run endpoint until the worker is done, like the UI does. */
async function finished(page: Page, runId: string): Promise<void> {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const response = await page.request.get(`${API}/api/v1/runs/${runId}`);
    const run = (await response.json()) as { state: string };
    if (["completed", "failed", "cancelled"].includes(run.state)) {
      expect(run.state, "the demo run must finish").toBe("completed");
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error(`Run ${runId} did not finish in two minutes.`);
}

test("the healthy demo becomes the baseline and the broken one blocks against it", async ({
  page,
}) => {
  test.setTimeout(300_000);
  const email = `baseline${Date.now()}@example.com`;
  await register(page, "Baseline User", email);

  const setup = await page.request.post(`${API}/api/v1/demo/load`);
  expect(setup.status(), await setup.text()).toBe(200);
  const demo = (await setup.json()) as DemoSetup;

  // The healthy app is the reference: the next run is compared with it.
  const baselineId = await startDemoRun(page, demo, demo.good_url, "Baseline — healthy");
  const baseline = await page.request.post(`${API}/api/v1/runs/${baselineId}/baseline`, {
    data: {},
  });
  expect(baseline.status(), await baseline.text()).toBe(201);

  const brokenId = await startDemoRun(page, demo, demo.broken_url, "Broken against baseline");

  // The verdict card shows the stored comparison, not a recomputed one.
  await page.goto(`${WEB}/results`);
  await page.getByTestId("run-history-open").first().click();
  await expect(page.getByTestId("run-detail-heading")).toContainText("Broken against baseline");
  await expect(page.getByTestId("run-verdict-word")).toHaveText("No-Go");
  await expect(page.getByTestId("regression-status")).toHaveText("Block");
  await expect(page.getByTestId("regression-reason")).toContainText("beyond the");
  await expect(page.getByTestId("regression-metrics")).toContainText("answer match");
  await expect(page.getByTestId("baseline-current")).toContainText("Baseline — healthy");

  // The same comparison is in the export.
  const report = await page.request.get(`${API}/api/v1/runs/${brokenId}/report?format=html`);
  expect(report.status(), await report.text()).toBe(200);
  const html = await report.text();
  expect(html).toContain("Regression");
  expect(html).toContain("BLOCK");
  expect(html).toContain("answer match");
});
