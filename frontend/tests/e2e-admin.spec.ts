import { test, expect } from '@playwright/test';

test('register, login, see admin role, upload CSV in Settings -> Datasets', async ({ page }) => {
  const email = `admin${Date.now()}@example.com`;
  
  // Register
  await page.goto('http://localhost:5177/register');
  await page.fill('input[aria-label="Name"], input[name="name"], input#name', 'Test Admin');
  await page.fill('input[type="email"], input[name="email"]', email);
  await page.fill('input[type="password"], input[name="password"]', 'password123456');
  await page.click('button[type="submit"]');
  
  await page.waitForURL(/http:\/\/localhost:5177\//);
  
  // See admin role in header
  await expect(page.locator('text=/admin/i')).toBeVisible();
  
  // Go to Settings -> Datasets
  await page.click('text=Settings');
  await page.waitForURL(/.*\/settings/);
  await page.click('text=Datasets');
  
  // Upload a small CSV
  const csvContent = 'input,output\nHello,World\nTest,Case\n';
  await page.setInputFiles('input[type="file"]', {
    name: 'test.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(csvContent),
  });
  await page.fill('input[placeholder*="name"], input#dataset-name', 'Test Dataset');
  await page.click('button:has-text("Upload")');
  
  // See it in the list
  await expect(page.locator('text=Test Dataset')).toBeVisible({ timeout: 10000 });
});
