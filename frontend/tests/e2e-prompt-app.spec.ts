import { test, expect, type Page } from "@playwright/test";
import { createServer } from "http";
import type { AddressInfo } from "net";

import { GUARDED_REFUSAL, isDisallowed } from "./guard";
import { ADMIN_EMAIL, createJudgeProfile, ensureAdmin, login, selectJudgeProfile } from "./helpers";

const WEB = process.env.E2E_BASE_URL ?? "http://localhost:5177";
const API = process.env.E2E_API_URL ?? "http://localhost:8003";
const MODEL = "fake-connector-model";

const ANSWERS: Record<string, string> = {
  "What is GreenLit?": "GreenLit tests LLM apps before launch.",
  "Is it fast?": "Yes, it runs in a worker.",
};

/** Two cases whose expected answers the fake provider below returns verbatim. */
const GOLDEN_CSV = [
  "question,answer",
  "What is GreenLit?,GreenLit tests LLM apps before launch.",
  "Is it fast?,Yes, it runs in a worker.",
].join("\n");

interface FakeProvider {
  port: number;
  close: () => Promise<void>;
}

/**
 * An OpenAI-compatible chat endpoint, so the run needs no real model.
 *
 * The gateway posts to `<base_url>/chat/completions`; the answer is picked from
 * the last user message, which is the dataset case input.
 */
function startFakeProvider(): Promise<FakeProvider> {
  return new Promise((resolve, reject) => {
    const server = createServer((req, res) => {
      if (req.method !== "POST" || req.url !== "/v1/chat/completions") {
        res.writeHead(404);
        res.end();
        return;
      }
      let body = "";
      req.on("data", (chunk) => {
        body += chunk;
      });
      req.on("end", () => {
        let question = "";
        try {
          const payload = JSON.parse(body) as {
            messages?: Array<{ role: string; content: string }>;
          };
          const messages = payload.messages ?? [];
          const system = messages
            .filter((message) => message.role === "system")
            .map((message) => message.content)
            .join("\n");
          const userMessages = messages.filter((m) => m.role === "user");
          const last = userMessages[userMessages.length - 1];
          question = typeof last?.content === "string" ? last.content : "";
          if (system.includes("Reply with ONLY a JSON object")) {
            res.writeHead(200, { "Content-Type": "application/json" });
            res.end(
              JSON.stringify({
                id: "fake-chat",
                object: "chat.completion",
                created: Math.floor(Date.now() / 1000),
                model: MODEL,
                choices: [
                  {
                    index: 0,
                    message: {
                      role: "assistant",
                      content: JSON.stringify({
                        score: 1,
                        reason: "The answer states the expected fact.",
                        confidence: 0.95,
                      }),
                    },
                    finish_reason: "stop",
                  },
                ],
                usage: { prompt_tokens: 120, completion_tokens: 40, total_tokens: 160 },
              }),
            );
            return;
          }
        } catch {
          question = "";
        }
        // The model under test refuses clearly disallowed requests, like a real
        // guarded prompt app: a missing refusal is a hard NO-GO (spec 8.3).
        const answer = isDisallowed(question)
          ? GUARDED_REFUSAL
          : (Object.entries(ANSWERS).find(([asked]) => question.includes(asked))?.[1] ??
            "GreenLit tests LLM apps before launch.");
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(
          JSON.stringify({
            id: "fake-chat",
            object: "chat.completion",
            created: Math.floor(Date.now() / 1000),
            model: MODEL,
            choices: [
              { index: 0, message: { role: "assistant", content: answer }, finish_reason: "stop" },
            ],
            // A real provider reports usage, and the operations block prices it.
            usage: { prompt_tokens: 120, completion_tokens: 40, total_tokens: 160 },
          }),
        );
      });
    });
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const addr = server.address() as AddressInfo;
      resolve({
        port: addr.port,
        close: () => new Promise<void>((done) => server.close(() => done())),
      });
    });
  });
}

/**
 * Add the saved provider the prompt-app form picks up, pointed at the fake server.
 *
 * The signed-in admin session is used because providers are admin-only.
 */
async function createFakeProvider(page: Page, provider: FakeProvider): Promise<string> {
  const created = await page.request.post(`${API}/api/v1/providers`, {
    data: {
      name: "Fake Prompt App Provider",
      kind: "openai-compatible",
      model_name: MODEL,
      base_url: `http://127.0.0.1:${provider.port}/v1`,
      connector: "prompt_app",
      timeout_seconds: 30,
      // The run probes the app 64 times for safety; this double absorbs that,
      // like a real provider does (the default 30/min would throttle it).
      rate_limit_per_minute: 600,
      is_active: true,
    },
  });
  expect(created.status(), await created.text()).toBe(201);
  return ((await created.json()) as { id: string }).id;
}

/** Upload a CSV and approve version 1, using the signed-in session's cookies. */
async function uploadApprovedDataset(page: Page, name: string): Promise<void> {
  const created = await page.request.post(`${API}/api/v1/datasets`, {
    multipart: {
      name,
      file: { name: "golden.csv", mimeType: "text/csv", buffer: Buffer.from(GOLDEN_CSV) },
    },
  });
  expect(created.status(), await created.text()).toBe(201);
  const dataset = (await created.json()) as { id: string };
  const approved = await page.request.post(
    `${API}/api/v1/datasets/${dataset.id}/versions/1/approve`,
  );
  expect(approved.status(), await approved.text()).toBe(200);
}

test("prompt app entry point runs a prompt to a verdict", async ({ page }) => {
  const provider = await startFakeProvider();
  try {
    await ensureAdmin();
    await login(page, ADMIN_EMAIL);
    const providerId = await createFakeProvider(page, provider);
    const judgeProfileId = await createJudgeProfile(page, {
      name: `Prompt app judge ${Date.now()}`,
      providerId,
      model: MODEL,
    });
    await selectJudgeProfile(page, judgeProfileId);

    // Token prices are set where a user sets them: the provider's own row in
    // Settings. They make the verdict show a cost estimate, not "not configured".
    await page.goto(`${WEB}/settings`);
    await page.getByTestId("settings-tab-providers-and-models").click();
    const priceRow = page.getByRole("row").filter({ hasText: "Fake Prompt App Provider" });
    // A provider nobody priced says so, rather than claiming the run was free.
    await expect(priceRow.getByTestId("provider-price-summary")).toHaveText("Tokens: not set");
    await priceRow.getByTestId("provider-price-edit").click();
    await page.getByTestId("provider-price-edit-in").fill("not-a-number");
    await page.getByTestId("provider-price-save").click();
    await expect(page.getByTestId("provider-price-error")).toContainText("Enter a number");
    await page.getByTestId("provider-price-edit-in").fill("0.01");
    await page.getByTestId("provider-price-edit-out").fill("0.02");
    await page.getByTestId("provider-price-save").click();
    await expect(priceRow.getByTestId("provider-price-summary")).toHaveText(
      "Tokens: in 0.01 / out 0.02 per 1K",
    );

    const datasetName = `Prompt Golden ${Date.now()}`;
    await uploadApprovedDataset(page, datasetName);

    await page.goto(`${WEB}/`);
    await page.waitForSelector('[data-testid="connector-select"]', { timeout: 20_000 });
    await page.selectOption('[data-testid="connector-select"]', "prompt_app");

    // The panel names the saved provider/model the run will use.
    await expect(page.getByTestId("prompt-provider-select")).toBeVisible({ timeout: 15_000 });
    await page.selectOption('[data-testid="prompt-provider-select"]', {
      label: "Fake Prompt App Provider",
    });
    await expect(page.getByTestId("prompt-app-model")).toHaveValue(MODEL);
    await expect(page.getByTestId("prompt-app-target")).toContainText(MODEL);

    await page.fill(
      '[data-testid="prompt-system-prompt"]',
      "You are a concise assistant. Answer in one sentence.",
    );
    await page.selectOption('[data-testid="prompt-app-dataset"]', {
      label: `${datasetName} · v1 (2 cases)`,
    });
    await page.getByLabel("Safety").uncheck();
    await page.getByLabel("Operations (latency, errors, tokens)").uncheck();

    // Start test itself creates the run through the runs API.
    await page.click('[data-testid="start-test"]');

    await expect(page.getByTestId("run-progress")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("run-verdict")).toBeVisible({ timeout: 90_000 });
    await expect(page.getByTestId("run-verdict-word")).toHaveText("Go");
    await expect(page.getByTestId("run-verdict-reason")).toContainText("GO threshold 0.80");
    await expect(page.getByTestId("run-state")).toHaveText("Completed");
    // The prompt-app connector really answered through the provider.
    await expect(page.getByTestId("run-metrics")).toContainText("answer match");

    // Operations carries the real tokens, and the price makes a real estimate.
    await expect(page.getByTestId("run-operations")).toBeVisible();
    await expect(page.getByTestId("ops-tokens-in")).not.toHaveText("not reported");
    await expect(page.getByTestId("ops-cost")).not.toHaveText("not configured");
    await expect(page.getByTestId("ops-cost")).toContainText("$");
    // Never a bare number: the arithmetic behind the estimate is shown.
    await expect(page.getByTestId("ops-cost-breakdown")).toContainText("per 1K tokens (estimate)");
    await expect(page.getByTestId("ops-cost-breakdown")).toContainText("×");
  } finally {
    await provider.close();
  }
});
