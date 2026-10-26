import { defineConfig } from "@playwright/test";

/**
 * The disposable e2e stack (scripts/run-e2e.sh) runs on its own ports so it
 * never touches the dev stack; it sets E2E_BASE_URL before invoking this suite.
 * Without it, the suite targets the normal dev stack at :5177.
 */
const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:5177";

export default defineConfig({
  testDir: "./tests",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  // The tests share one database and assert in registration order (the first
  // account must be admin), so they run serially in one worker.
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
