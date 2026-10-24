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
          } catch (e) {
            // ignore
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

test("register, login, see admin role, upload CSV in Settings -> Datasets", async ({ page }) => {
  const email = `admin${Date.now()}@example.com`;

  // Register
  await page.goto("http://localhost:5177/register");
  await page.fill('#register-name, input[name="name"]', "Test Admin");
  await page.fill('#register-email, input[type="email"], input[name="email"]', email);
  await page.fill('#register-password, input[type="password"]', "password123456");
  await page.click('button[type="submit"]');

  await page.waitForURL(/http:\/\/localhost:5177\//);

  // See admin role in header
  await expect(page.locator("text=/admin/i")).toBeVisible();

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
  await expect(page.locator("text=Test Dataset")).toBeVisible({ timeout: 10000 });
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
  console.log('URL:', page.url());
  if (page.url().includes('/login')) {
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
  await page.waitForSelector('[data-testid="detect-result"]', { timeout: 60000 });
  const pageContent = await page.content();
  console.log('HAS_DETECT:', pageContent.includes('detect-result'));
  const errorEl = page.locator('.form-error');
  if (await errorEl.count() > 0) {
    try {
      const errorText = await errorEl.first().textContent();
      console.log('ERROR:', errorText);
    } catch (e) {
      // ignore
    }
  }
  await expect(page.locator('[data-testid="detected-request-shape"]')).toBeVisible();
  await expect(page.locator('[data-testid="detected-answer-path"]')).toBeVisible();
  await expect(page.locator('[data-testid="detected-context-path"]')).toBeVisible();
});
