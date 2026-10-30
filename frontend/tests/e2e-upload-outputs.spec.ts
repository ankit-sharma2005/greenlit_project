import { test, expect } from "@playwright/test";

import { GOLDEN_CSV, openNewTestPage, register, uploadApprovedDataset } from "./helpers";

/** Uploaded outputs: the app already ran, so the run scores the file we upload. */
const UPLOAD_CSV = [
  "input,output",
  '"What is GreenLit?","GreenLit tests LLM apps before launch."',
  '"Is it fast?","Yes, it runs in a worker."',
].join("\n");

test("uploaded outputs are scored against the approved dataset and reach a verdict", async ({
  page,
}) => {
  test.setTimeout(180_000);

  await register(page, "Upload User", `upload${Date.now()}@example.com`);
  const dataset = await uploadApprovedDataset(page, `Upload golden ${Date.now()}`, GOLDEN_CSV);

  await openNewTestPage(page);
  await page.selectOption('[data-testid="connector-select"]', "upload_outputs");

  // The file input behind the drop area, so no native chooser is involved.
  await page.setInputFiles('[data-testid="upload-file-input"]', {
    name: "outputs.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(UPLOAD_CSV),
  });

  // Auto-detect lists the headers, and both required columns are mapped.
  await expect(page.getByTestId("upload-column-badge").first()).toBeVisible({ timeout: 15_000 });
  await page.selectOption('[data-testid="upload-col-input"]', "input");
  await page.selectOption('[data-testid="upload-col-output"]', "output");
  await page.selectOption('[data-testid="upload-dataset"]', { label: dataset.label });

  await page.click('[data-testid="start-test"]');

  // The same progress panel and verdict card as the other entry points.
  await expect(page.getByTestId("run-progress")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("run-verdict")).toBeVisible({ timeout: 90_000 });
  await expect(page.getByTestId("run-verdict-word")).toHaveText("Go");
  await expect(page.getByTestId("run-verdict-score")).toHaveText("1.00");
  await expect(page.getByTestId("run-verdict-reason")).toContainText("GO threshold 0.80");
  await expect(page.getByTestId("run-metrics")).toContainText("answer match");
  await expect(page.getByTestId("run-state")).toHaveText("Completed");

  // Operations travels with the verdict and never invents a cost estimate.
  await expect(page.getByTestId("run-operations")).toBeVisible();
  await expect(page.getByTestId("ops-cost")).toHaveText("not configured");
});
