import { test, expect, type Page } from "@playwright/test";
import { createServer } from "http";
import type { AddressInfo } from "net";

const WEB = process.env.E2E_BASE_URL ?? "http://localhost:5177";
/** Host the API uses to reach the fake app this file starts (docker: host.docker.internal). */
const TARGET_HOST = process.env.E2E_TARGET_HOST ?? "127.0.0.1";
const PASSWORD = "password123456";

interface QuestionApp {
  port: number;
  close: () => Promise<void>;
}

/** Tiny app that only answers the {"question": ...} shape, so auto-detect has a real target. */
function startQuestionApp(): Promise<QuestionApp> {
  return new Promise((resolve, reject) => {
    const server = createServer((req, res) => {
      if (req.method === "POST") {
        let body = "";
        req.on("data", (chunk) => {
          body += chunk;
        });
        req.on("end", () => {
          try {
            const data = JSON.parse(body);
            if ("question" in data) {
              res.writeHead(200, { "Content-Type": "application/json" });
              res.end(JSON.stringify({ answer: "hello" }));
              return;
            }
          } catch {
            // not JSON: fall through to the 400 below
          }
          res.writeHead(400);
          res.end();
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

test("register, login, see the admin role, upload CSV in Settings -> Datasets", async ({
  page,
}) => {
  const email = `admin${Date.now()}@example.com`;

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
