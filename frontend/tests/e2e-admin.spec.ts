import { test, expect, type Page } from "@playwright/test";
import { createServer } from "http";
import type { AddressInfo } from "net";

import { GUARDED_REFUSAL, isDisallowed } from "./guard";

const WEB = process.env.E2E_BASE_URL ?? "http://localhost:5177";
const API = process.env.E2E_API_URL ?? "http://localhost:8003";
/** Host the API uses to reach the fake app this file starts (docker: host.docker.internal). */
const TARGET_HOST = process.env.E2E_TARGET_HOST ?? "127.0.0.1";
const PASSWORD = "password123456";

const GOLDEN_ANSWERS: Record<string, string> = {
  "What is GreenLit?": "GreenLit tests LLM apps before launch.",
  "Is it fast?": "Yes, it runs in a worker.",
};

const GOLDEN_CSV = [
  "question,answer",
  "What is GreenLit?,GreenLit tests LLM apps before launch.",
  "Is it fast?,Yes, it runs in a worker.",
].join("\n");

/** Six cases against the slow app, so there is time to cancel mid-run. */
const SLOW_CSV = [
  "question,answer",
  ...Array.from({ length: 3 }, () => [
    "What is GreenLit?,GreenLit tests LLM apps before launch.",
    "Is it fast?,Yes, it runs in a worker.",
  ]).flat(),
].join("\n");

interface FakeApp {
  port: number;
  close: () => Promise<void>;
}

type Reply = Record<string, unknown> | null;

/** Tiny JSON app: the handler decides the reply, a null reply means HTTP 400. */
function startApp(reply: (data: Record<string, unknown>) => Reply, delayMs = 0): Promise<FakeApp> {
  return new Promise((resolve, reject) => {
    const server = createServer((req, res) => {
      if (req.method === "POST") {
        let body = "";
        req.on("data", (chunk) => {
          body += chunk;
        });
        req.on("end", () => {
          let payload: Reply = null;
          try {
            payload = reply(JSON.parse(body) as Record<string, unknown>);
          } catch {
            payload = null;
          }
          if (payload === null) {
            res.writeHead(400);
            res.end();
            return;
          }
          const answer = () => {
            res.writeHead(200, { "Content-Type": "application/json" });
            res.end(JSON.stringify(payload));
          };
          if (delayMs > 0) {
            setTimeout(answer, delayMs);
          } else {
            answer();
          }
        });
        return;
      }
      res.writeHead(200);
      res.end("ok");
    });
    server.on("error", reject);
    // Bound on all interfaces so an API running in Docker can reach it too.
    server.listen(0, "0.0.0.0", () => {
      const addr = server.address() as AddressInfo;
      resolve({
        port: addr.port,
        close: () => new Promise<void>((done) => server.close(() => done())),
      });
    });
  });
}

/** Only answers the {"question": ...} shape, so auto-detect has a real target. */
function startQuestionApp(): Promise<FakeApp> {
  return startApp((data) => ("question" in data ? { answer: "hello" } : null));
}

/** A healthy helpdesk app: correct answers plus a context passage.
 *
 * The probe question auto-detect sends is not one of the golden questions, so
 * unknown inputs get a plain fallback rather than an error: detection must see
 * a real 2xx response, and the dataset cases still get their exact answers.
 */
function startGoldenApp(delayMs = 0): Promise<FakeApp> {
  return startApp((data) => {
    const question = typeof data.question === "string" ? data.question : "";
    // A healthy app declines clearly disallowed requests: the safety probes
    // treat a missing refusal as a hard NO-GO (spec 8.3).
    if (isDisallowed(question)) {
      return { answer: GUARDED_REFUSAL, context: "The helpdesk refuses harmful requests." };
    }
    const answer = GOLDEN_ANSWERS[question] ?? "I am not sure about that.";
    return { answer, context: `${answer} (helpdesk handbook)` };
  }, delayMs);
}

/** Register a fresh account and return the role the API assigned it. */
async function register(page: Page, name: string, email: string): Promise<string> {
  await page.goto(`${WEB}/register`);
  await page.fill('#register-name, input[name="name"]', name);
  await page.fill('#register-email, input[type="email"], input[name="email"]', email);
  await page.fill('#register-password, input[type="password"]', PASSWORD);
  const registered = page.waitForResponse(
    (response) => response.url().includes("/api/v1/auth/register") && response.status() === 201,
  );
  await page.click('button[type="submit"]');
  const body = (await (await registered).json()) as { user: { role: string } };
  await page.waitForURL((url) => !url.pathname.includes("/register"), { timeout: 15_000 });
  return body.user.role;
}

/** Upload a CSV and approve version 1, using the signed-in session's cookies. */
async function uploadApprovedDataset(page: Page, name: string, csv: string): Promise<void> {
  const created = await page.request.post(`${API}/api/v1/datasets`, {
    multipart: {
      name,
      file: { name: "golden.csv", mimeType: "text/csv", buffer: Buffer.from(csv) },
    },
  });
  expect(created.status(), await created.text()).toBe(201);
  const dataset = (await created.json()) as { id: string };
  const approved = await page.request.post(
    `${API}/api/v1/datasets/${dataset.id}/versions/1/approve`,
  );
  expect(approved.status(), await approved.text()).toBe(200);
}

/** Land on the New Test page, signing in first if the session did not survive navigation. */
async function openNewTestPage(page: Page): Promise<void> {
  await page.goto(`${WEB}/`);
  const outcome = await Promise.race([
    page
      .waitForSelector('[data-testid="connector-select"]', { timeout: 20_000 })
      .then(() => "ready" as const),
    page
      .waitForSelector('input[type="password"]', { timeout: 20_000 })
      .then(() => "login" as const),
  ]);
  if (outcome === "login") {
    throw new Error(`Redirected to the login page at ${page.url()} while ${WEB}/ was expected.`);
  }
}

/** Fill the one-box flow and press Start test until the detected panel appears. */
async function detectTarget(page: Page, app: FakeApp): Promise<void> {
  await page.selectOption('[data-testid="connector-select"]', "http_endpoint");
  await page.fill('[data-testid="target-url"]', `http://${TARGET_HOST}:${app.port}/chat`);
  await page.check("#runs-on-my-computer");
  await page.click('[data-testid="start-test"]');
  await expect(page.getByTestId("detect-result")).toBeVisible({ timeout: 60_000 });
}

test("register, login, see the admin role, upload CSV in Settings -> Datasets", async ({
  page,
}) => {
  // Fixed address: later specs sign in as this admin to seed admin-only data.
  const email = "admin@example.com";

  // First account on the fresh e2e database: the API must assign "admin".
  const role = await register(page, "Test Admin", email);
  expect(role).toBe("admin");

  // The header must show the role the API reports.
  await expect(page.getByTestId("user-role")).toHaveText("admin");

  // Go to Settings -> Datasets
  await page.click("text=Settings");
  await page.waitForURL(/.*\/settings/);
  await page.click("text=Datasets");

  // Upload a small CSV
  const csvContent = "input,output\nHello,World\nTest,Case\n";
  await page.setInputFiles('input[type="file"]', {
    name: "test.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(csvContent),
  });
  await page.fill('input[placeholder*="name"], input#dataset-name', "Test Dataset");
  await page.click('button:has-text("Upload")');

  // See it in the list
  await expect(page.getByTestId("datasets-table").getByText("Test Dataset")).toBeVisible({
    timeout: 10_000,
  });
});

test("results page scores outputs and explains the verdict", async ({ page }) => {
  const email = `results${Date.now()}@example.com`;
  await register(page, "Results User", email);

  await page.goto(`${WEB}/results`);
  await page.waitForSelector('[data-testid="outputs-csv"]', { timeout: 20_000 });

  // The broken outputs must be a NO-GO whose reason names the threshold.
  await page.click('button:has-text("Load broken example")');
  await page.click('[data-testid="evaluate-button"]');
  await expect(page.getByTestId("verdict-word")).toHaveText("No-Go", { timeout: 30_000 });
  await expect(page.getByTestId("verdict-reason")).toContainText("REVIEW threshold 0.60");
  await expect(page.getByTestId("verdict-reason")).toContainText("answer_match 0.00");
  await expect(page.getByTestId("metrics-table")).toContainText("answer match");
  await expect(page.getByTestId("failed-cases")).toContainText("I am not sure about that.");

  // The good outputs must be a GO.
  await page.click('button:has-text("Load good example")');
  await page.click('[data-testid="evaluate-button"]');
  await expect(page.getByTestId("verdict-word")).toHaveText("Go", { timeout: 30_000 });
  await expect(page.getByTestId("verdict-reason")).toContainText("GO threshold 0.80");
});

test("new test page auto-detects the question shape", async ({ page }) => {
  const app = await startQuestionApp();
  try {
    const email = `detect${Date.now()}@example.com`;
    await register(page, "Detect User", email);

    await openNewTestPage(page);
    await page.selectOption('[data-testid="connector-select"]', "http_endpoint");
    await page.fill('[data-testid="target-url"]', `http://${TARGET_HOST}:${app.port}/test`);
    await page.check("#runs-on-my-computer");
    await page.click('[data-testid="start-test"]');

    // What auto-detect found, from the real request/response pair:
    await expect(page.getByTestId("detect-result")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("detected-request-shape")).toContainText("question");
    await expect(page.getByTestId("detected-answer-path")).toContainText("answer");
    await expect(page.getByTestId("detected-context-path")).toBeVisible();
    // The real response body is shown so the user can verify what came back.
    await expect(page.getByTestId("detect-result")).toContainText("Real response");
  } finally {
    await app.close();
  }
});

test("new test page runs a test to a GO verdict", async ({ page }) => {
  // The run also probes the app for safety (44 attacks plus 26 safe prompts), so
  // a slow machine needs more than the default budget to reach the verdict.
  test.setTimeout(180_000);
  const app = await startGoldenApp();
  try {
    const email = `run${Date.now()}@example.com`;
    await register(page, "Run User", email);
    const datasetName = `Golden ${Date.now()}`;
    await uploadApprovedDataset(page, datasetName, GOLDEN_CSV);

    await openNewTestPage(page);
    await detectTarget(page, app);

    await page.selectOption('[data-testid="run-dataset"]', {
      label: `${datasetName} · v1 (2 cases)`,
    });
    await page.click('[data-testid="run-test"]');

    // Live progress comes from the worker, polled by the page.
    await expect(page.getByTestId("run-progress")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("run-counters")).toContainText("cases done");

    // Then the stored verdict, with the engine's own explanation.
    await expect(page.getByTestId("run-verdict")).toBeVisible({ timeout: 120_000 });
    await expect(page.getByTestId("run-verdict-word")).toHaveText("Go");
    await expect(page.getByTestId("run-verdict-score")).toHaveText("1.00");
    await expect(page.getByTestId("run-verdict-reason")).toContainText("GO threshold 0.80");
    await expect(page.getByTestId("run-metrics")).toContainText("answer match");
    await expect(page.getByTestId("run-state")).toHaveText("Completed");
  } finally {
    await app.close();
  }
});

test("results page lists runs, opens a verdict and compares two runs", async ({ page }) => {
  // Two full runs, and each one also probes the app for safety (44 attacks plus
  // the safe set), so the default 90s budget is not enough.
  test.setTimeout(240_000);
  const app = await startGoldenApp();
  try {
    const email = `history${Date.now()}@example.com`;
    await register(page, "History User", email);
    const datasetName = `History ${Date.now()}`;
    await uploadApprovedDataset(page, datasetName, GOLDEN_CSV);

    // Two completed runs from the same account, through the normal UI flow.
    await openNewTestPage(page);
    await detectTarget(page, app);
    await page.getByLabel("Safety").uncheck();
    await page.getByLabel("Operations (latency, errors, tokens)").uncheck();
    await page.selectOption('[data-testid="run-dataset"]', {
      label: `${datasetName} · v1 (2 cases)`,
    });
    await page.click('[data-testid="run-test"]');
    await expect(page.getByTestId("run-verdict-word")).toHaveText("Go", { timeout: 60_000 });

    await page.click('[data-testid="run-test"]');
    await expect(page.getByTestId("run-verdict-word")).toHaveText("Go", { timeout: 60_000 });

    // Both runs are in the history with their stored verdict.
    await page.goto(`${WEB}/results`);
    await expect(page.getByTestId("run-history")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("run-history-row")).toHaveCount(2);
    await expect(page.getByTestId("run-history-verdict").first()).toHaveText("Go");
    await expect(page.getByTestId("run-history-score").first()).toHaveText("1.00");

    // Opening a run shows its verdict card, the same component the New Test page uses.
    await page.getByTestId("run-history-open").first().click();
    await expect(page.getByTestId("run-verdict")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("run-verdict-score")).toHaveText("1.00");

    // Compare the two runs side by side.
    const selects = page.getByTestId("run-history-select");
    await selects.nth(0).check();
    await selects.nth(1).check();
    await page.click('[data-testid="run-history-compare"]');

    await expect(page.getByTestId("run-compare")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("compare-baseline-verdict")).toHaveText("Go");
    await expect(page.getByTestId("compare-candidate-verdict")).toHaveText("Go");
    await expect(page.getByTestId("compare-score-delta")).toHaveText("+0.00");
    await expect(page.getByTestId("run-compare-row").first()).toContainText("answer match");
  } finally {
    await app.close();
  }
});

test("cancel stops a running test and keeps partial results", async ({ page }) => {
  const app = await startGoldenApp(2500);
  try {
    const email = `cancel${Date.now()}@example.com`;
    await register(page, "Cancel User", email);
    const datasetName = `Slow ${Date.now()}`;
    await uploadApprovedDataset(page, datasetName, SLOW_CSV);

    await openNewTestPage(page);
    await detectTarget(page, app);
    await page.selectOption('[data-testid="run-dataset"]', {
      label: `${datasetName} · v1 (6 cases)`,
    });
    await page.click('[data-testid="run-test"]');

    await expect(page.getByTestId("run-progress")).toBeVisible({ timeout: 15_000 });
    await page.click('[data-testid="cancel-run"]');

    await expect(page.getByTestId("run-state")).toContainText("partial results", {
      timeout: 60_000,
    });
    await expect(page.getByTestId("run-verdict-reason")).toContainText("cancelled");
    await expect(page.getByTestId("cancel-run")).not.toBeVisible();
  } finally {
    await app.close();
  }
});
