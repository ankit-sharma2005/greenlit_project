import { test, expect } from "@playwright/test";

import { WEB, register } from "./helpers";

test("website chatbot wizard checks the local demo and keeps HTTP endpoint flow working", async ({
  page,
}) => {
  test.setTimeout(180_000);

  await register(page, "Website Wizard User", `website-wizard${Date.now()}@example.com`);
  await page.goto(`${WEB}/`);
  await expect(page.getByTestId("connector-select")).toBeVisible({ timeout: 20_000 });
  await page.getByRole("button", { name: "Website chatbot (wizard)" }).click();

  await page.getByTestId("permission-confirmed").check();
  await page.getByTestId("permission-reference").fill("local e2e demo authorization");
  await page.getByLabel("This app runs on my computer").check();
  const curlInput = page.getByTestId("website-curl");
  await curlInput.fill(
    `curl -X POST http://127.0.0.1:9501/chat -H "Content-Type: application/json" -d '{"question":"What is the Merit Scholarship?"}'`,
  );
  await page.getByTestId("website-message").fill("What is the Merit Scholarship?");
  await page.getByTestId("website-read").click();

  await expect(curlInput).toHaveValue("");
  await expect(page.getByTestId("website-check-answer")).toContainText(
    "The Merit Scholarship is a merit-based award for first-year students.",
    { timeout: 30_000 },
  );
  const answerCandidate = page.getByTestId("website-candidate-0");
  await expect(answerCandidate).toBeVisible();
  await expect(answerCandidate).toHaveValue("answer");
  await expect(page.getByTestId("website-candidate-1")).toHaveValue("context");
  await answerCandidate.check();

  await expect(page.getByTestId("website-accept")).toBeEnabled({ timeout: 30_000 });
  await expect(page.getByTestId("run-full")).toBeDisabled();
  await page.getByTestId("website-accept").click();
  await expect(page.getByTestId("website-accept")).toBeChecked({ timeout: 30_000 });
  await expect(page.getByTestId("run-full")).toBeEnabled({ timeout: 30_000 });

  await curlInput.fill("curl -X GET http://127.0.0.1:9501/chat");
  await page.getByTestId("website-read").click();
  await expect(page.getByRole("alert")).toContainText(
    "This request uses method GET. GreenLit sends POST today.",
  );

  await page.getByRole("button", { name: "Close" }).click();
  await page.getByTestId("start-test").click();
  await expect(page.getByTestId("detect-result")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("detected-request-shape")).toContainText('"question"');
});