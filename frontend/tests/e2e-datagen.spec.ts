/**
 * Dataset drafts: generate, review item by item, publish the approved ones.
 *
 * The provider is the fake OpenAI-compatible server from the shared helpers, so no
 * real model is called. The proof is that the published dataset contains exactly the
 * approved and edited questions — not the rejected one — and carries the generator's
 * provenance.
 */

import path from "node:path";

import { expect, test } from "@playwright/test";

import { API, WEB, createProvider, register, startFakeProvider } from "./helpers";

const SCREENS = path.resolve(process.cwd(), "..", "local-prompts", "screens");

const GENERATED = JSON.stringify([
  {
    question: "What is the refund window?",
    expected_answer: "Thirty days from delivery.",
    source_passage: "Refunds are accepted within thirty days of delivery.",
    kind: "document_fact",
  },
  {
    question: "Do you ship internationally?",
    expected_answer: "Yes, to 30 countries.",
    source_passage: "We ship to 30 countries.",
    kind: "document_fact",
  },
  {
    question: "Can I cancel an order?",
    expected_answer: "Yes, before it ships.",
    source_passage: null,
    kind: "unanswerable",
  },
]);

test("a draft is generated, reviewed, and only approved items are published", async ({ page }) => {
  test.setTimeout(300_000);
  const fake = await startFakeProvider({ generationReply: GENERATED });
  try {
    await register(page, "Draft User", `draft${Date.now()}@example.com`);

    const providerName = `Draft provider ${Date.now()}`;
    await createProvider(page, {
      name: providerName,
      model: "llama3",
      baseUrl: `http://127.0.0.1:${fake.port}/v1`,
    });

    await page.goto(`${WEB}/settings`);
    await page.getByTestId("settings-tab-datasets").click();
    await expect(page.getByTestId("draft-generator")).toBeVisible();

    const datasetName = `Reviewed draft ${Date.now()}`;
    await page.getByTestId("draft-name").fill(datasetName);
    await page
      .getByTestId("draft-description")
      .fill("A support assistant for an online shop that answers refund and shipping questions.");
    await page.getByTestId("draft-count").fill("3");
    await page.getByTestId("draft-kind-unanswerable").check();

    const providerSelect = page.getByTestId("draft-provider");
    const optionValue = await providerSelect
      .locator("option", { hasText: providerName })
      .getAttribute("value");
    expect(optionValue, "the created provider must be selectable").toBeTruthy();
    await providerSelect.selectOption(optionValue!);
    await expect(page.getByTestId("draft-model")).toHaveValue("llama3");

    await page.getByTestId("draft-generate").click();
    await expect(page.getByTestId("draft-review")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("draft-count-pending")).toContainText("3 pending");

    const rows = page.locator('[data-testid^="draft-item-"]').filter({ hasText: "Question" });
    void rows;

    // Approve the first, reject the second, edit the third and approve it.
    const items = page.locator('tr[data-testid^="draft-item-"]');
    await expect(items).toHaveCount(3);
    const first = items.nth(0);
    const second = items.nth(1);
    const third = items.nth(2);

    await first.getByRole("button", { name: "Approve" }).click();
    await expect(page.getByTestId("draft-count-approved")).toContainText("1 approved");

    await second.getByRole("button", { name: "Reject" }).click();
    await expect(page.getByTestId("draft-count-rejected")).toContainText("1 rejected");

    await third.getByRole("button", { name: "Edit" }).click();
    const questionBox = third.getByLabel("Question");
    await questionBox.fill("Can I cancel an order after it ships?");
    await third.getByRole("button", { name: "Save" }).click();
    await third.getByRole("button", { name: "Approve" }).click();
    await expect(page.getByTestId("draft-count-approved")).toContainText("2 approved");

    // Publishing is only enabled because something is approved.
    await expect(page.getByTestId("draft-publish")).toBeEnabled();
    await page.screenshot({ path: path.join(SCREENS, "after-draft-review-1280x800-dark.png") });
    await page.getByTestId("draft-publish").click();
    await expect(page.getByTestId("draft-review-notice")).toContainText(
      "only approved items are included",
      { timeout: 30_000 },
    );

    // The dataset holds exactly the approved items, and says what generated it.
    const list = await page.request.get(`${API}/api/v1/datasets`);
    const datasets = (await list.json()) as { items: Array<{ id: string; name: string }> };
    const published = datasets.items.find((entry) => entry.name === datasetName);
    expect(published, "the published dataset must exist").toBeTruthy();

    const versions = await page.request.get(`${API}/api/v1/datasets/${published!.id}/versions`);
    const versionList = (await versions.json()) as Array<{
      version_no: number;
      row_count: number;
      generated: boolean;
      columns_snapshot: Record<string, unknown> | null;
      approved_at: string | null;
    }>;
    expect(versionList).toHaveLength(1);
    expect(versionList[0]!.row_count).toBe(2);
    expect(versionList[0]!.generated).toBe(true);
    expect(versionList[0]!.approved_at).not.toBeNull();
    const snapshot = versionList[0]!.columns_snapshot ?? {};
    expect(snapshot["generated_by_model"]).toBe("llama3");
    expect(snapshot["prompt_version"]).toBe("draft-v1");
    expect(snapshot["approved_items"]).toBe(2);

    const itemsResponse = await page.request.get(
      `${API}/api/v1/datasets/${published!.id}/versions/1/items`,
    );
    const itemList = (await itemsResponse.json()) as {
      items: Array<{ data: { question: string } }>;
    };
    const questions = itemList.items.map((entry) => entry.data.question);
    expect(questions).toContain("Can I cancel an order after it ships?");
    expect(questions).not.toContain("Do you ship internationally?");
    expect(questions).not.toContain("Can I cancel an order?");
  } finally {
    await fake.close();
  }
});
