import { test, expect } from "@playwright/test";
import { createServer } from "http";

function startQuestionApp() {
  return new Promise<number>((resolve) => {
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
    server.listen(0, "127.0.0.1", () => {
      const addr = server.address();
      if (addr && typeof addr === "object") {
        resolve(addr.port);
      } else {
        resolve(0);
      }
    });
  });
}

test("register, login, see the real role, upload CSV in Settings -> Datasets", async ({ page }) => {
  const email = `admin${Date.now()}@example.com`;

  // Register
  await page.goto("http://localhost:5177/register");
  await page.fill('#register-name, input[name="name"]', "Test Admin");
  await page.fill('#register-email, input[type="email"], input[name="email"]', email);
  await page.fill('#register-password, input[type="password"]', "password123456");
  const registerResponse = page.waitForResponse(
    (response) => response.url().includes("/api/v1/auth/register") && response.status() === 201,
  );
  await page.click('button[type="submit"]');
  const role = ((await (await registerResponse).json()) as { user: { role: string } }).user.role;

  await page.waitForURL(/http:\/\/localhost:5177\//);

  // The header must show the role the API reports. On an empty database that is
  // "admin" (first account); on a database that already has users it is "member".
  // The first-user-is-admin rule itself is asserted in backend tests/test_auth.py.
  expect(["admin", "member", "reviewer"]).toContain(role);
  await expect(page.getByTestId("user-role")).toHaveText(role);

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
    timeout: 10000,
  });
});

test("results page scores outputs and explains the verdict", async ({ page }) => {
  const email = `results${Date.now()}@example.com`;
  await page.context().clearCookies();

  await page.goto("http://localhost:5177/register");
  await page.fill('#register-name, input[name="name"]', "Results User");
  await page.fill('#register-email, input[type="email"], input[name="email"]', email);
  await page.fill('#register-password, input[type="password"]', "password123456");
  await page.click('button[type="submit"]');
  await page.waitForURL((url) => !url.pathname.includes("/register"), { timeout: 15000 });

  await page.goto("http://localhost:5177/results");
  await page.waitForSelector('[data-testid="outputs-csv"]', { timeout: 20000 });

  // The broken outputs must be a NO-GO whose reason names the threshold.
  await page.click('button:has-text("Load broken example")');
  await page.click('[data-testid="evaluate-button"]');
  await expect(page.getByTestId("verdict-word")).toHaveText("No-Go", { timeout: 30000 });
  await expect(page.getByTestId("verdict-reason")).toContainText("REVIEW threshold 0.60");
  await expect(page.getByTestId("verdict-reason")).toContainText("answer_match 0.00");
  await expect(page.getByTestId("metrics-table")).toContainText("answer match");
  await expect(page.getByTestId("failed-cases")).toContainText("I am not sure about that.");

  // The good outputs must be a GO.
  await page.click('button:has-text("Load good example")');
  await page.click('[data-testid="evaluate-button"]');
  await expect(page.getByTestId("verdict-word")).toHaveText("Go", { timeout: 30000 });
  await expect(page.getByTestId("verdict-reason")).toContainText("GO threshold 0.80");
});

test("new test page auto-detects question shape", async ({ page }) => {
  const port = await startQuestionApp();
  const email = `user2${Date.now()}@example.com`;

  // Clear cookies/storage
  await page.context().clearCookies();

  await page.goto("http://localhost:5177/register");
  await page.fill('#register-name, input[name="name"]', "Test User2");
  await page.fill('#register-email, input[type="email"], input[name="email"]', email);
  await page.fill('#register-password, input[type="password"]', "password123456");
  await page.click('button[type="submit"]');

  await page.waitForURL((url) => !url.pathname.includes('/register'), { timeout: 15000 });
  await page.waitForTimeout(2000);

  await page.goto("http://localhost:5177/");
  await page.waitForTimeout(3000);
  if (page.url().includes("/login")) {
    await page.goto("http://localhost:5177/login");
    await page.fill('input[type="email"]', email);
    await page.fill('input[type="password"]', "password123456");
    await page.click('button[type="submit"]');
    await page.waitForURL((url) => !url.pathname.includes('/login'), { timeout: 15000 });
    await page.goto("http://localhost:5177/");
    await page.waitForTimeout(3000);
  }
  await page.waitForSelector('[data-testid="connector-select"]', { timeout: 30000 });
  await page.selectOption('[data-testid="connector-select"]', "http_endpoint");
  await page.fill('[data-testid="target-url"]', `http://127.0.0.1:${port}/test`);
  await page.check('#runs-on-my-computer');
  await page.click('[data-testid="start-test"]');
  await expect(page.locator('[data-testid="detect-result"]')).toBeVisible({ timeout: 60000 });
  await expect(page.locator('[data-testid="detected-request-shape"]')).toBeVisible();
  await expect(page.locator('[data-testid="detected-answer-path"]')).toBeVisible();
  await expect(page.locator('[data-testid="detected-context-path"]')).toBeVisible();
});
