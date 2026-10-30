import { test, expect } from "@playwright/test";

import {
  ADMIN_EMAIL,
  createProvider,
  ensureAdmin,
  login,
  startFakeProvider,
  TARGET_HOST,
  uploadApprovedDataset,
  WEB,
} from "./helpers";

function samplePdf(): Buffer {
  const stream = "BT /F1 12 Tf 72 720 Td (The scholarship covers tuition.) Tj ET";
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] " +
      "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
    `<< /Length ${Buffer.byteLength(stream)} >>\nstream\n${stream}\nendstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];
  let pdf = "%PDF-1.4\n";
  const offsets = [0];
  for (const [index, object] of objects.entries()) {
    offsets.push(Buffer.byteLength(pdf));
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`;
  }
  const xrefOffset = Buffer.byteLength(pdf);
  pdf += `xref\n0 ${offsets.length}\n0000000000 65535 f \n`;
  pdf += offsets
    .slice(1)
    .map((offset) => `${String(offset).padStart(10, "0")} 00000 n \n`)
    .join("");
  pdf += `trailer\n<< /Size ${offsets.length} /Root 1 0 R >>\n`;
  pdf += `startxref\n${xrefOffset}\n%%EOF\n`;
  return Buffer.from(pdf);
}

test("Dataset Studio generates, previews and approves cases from an uploaded PDF", async ({
  page,
}) => {
  // Providers are admin-only, so this uses the admin account like the judge
  // spec; the dataset it opens is filtered by its own unique name below.
  await ensureAdmin();
  await login(page, ADMIN_EMAIL);
  const datasetName = `PDF generation seed ${Date.now()}`;

  const fakeProvider = await startFakeProvider({
    generationReply: JSON.stringify([
      {
        question: "What does the scholarship cover?",
        answer: "Tuition.",
        passage_index: 0,
      },
    ]),
  });
  try {
    const providerId = await createProvider(page, {
      name: "PDF generation fake",
      model: "fake-model",
      baseUrl: `http://${TARGET_HOST}:${fakeProvider.port}/v1`,
    });
    await uploadApprovedDataset(page, datasetName, "question,answer\nSeed,Answer\n");

    await page.goto(`${WEB}/settings`);
    await page.getByTestId("settings-tab-datasets").click();
    await page
      .getByTestId("datasets-table")
      .getByRole("row")
      .filter({ hasText: datasetName })
      .getByTestId("open-dataset")
      .click();
    await page.selectOption('[data-testid="generate-provider"]', providerId);
    await page.setInputFiles('[data-testid="generate-source-file"]', {
      name: "scholarship.pdf",
      mimeType: "application/pdf",
      buffer: samplePdf(),
    });
    await page.getByTestId("generate-submit").click();

    // The draft is generated, then previewed with the passage each case came from.
    await expect(page.getByTestId("datasets-notice")).toContainText(
      "Draft version 2 generated with 1 cases.",
    );
    await expect(page.getByTestId("dataset-preview")).toBeVisible();
    await expect(page.getByTestId("preview-passage").first()).toContainText(
      "The scholarship covers tuition.",
    );

    await page.getByTestId("approve-version").click();
    await expect(page.getByTestId("datasets-notice")).toContainText("Version 2 is approved");
    await expect(page.getByText("Approved", { exact: true })).toHaveCount(2);
  } finally {
    await fakeProvider.close();
  }
});
