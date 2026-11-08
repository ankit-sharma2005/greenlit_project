/**
 * The app shell has to use the whole window at every size.
 *
 * Two tests: one proves the invariants (shell equals the viewport, no horizontal
 * page scroll, the main region — not the document — is what scrolls on a long
 * page), the other writes the screenshots the layout work was judged by.
 */

import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { register, WEB } from "./helpers";

/** Set per run: "before" or "after" the layout work. */
const PREFIX = "after";

const SCREENS = path.resolve(process.cwd(), "..", "local-prompts", "screens");

const SIZES = [
  { width: 1920, height: 1080 },
  { width: 1440, height: 900 },
  { width: 1280, height: 800 },
  { width: 375, height: 800 },
];

const PAGES = [
  { name: "new-test", url: "/" },
  { name: "results", url: "/results" },
  { name: "test-chat", url: "/test-chat" },
] as const;

async function signIn(page: Page): Promise<void> {
  await page.setViewportSize(SIZES[0] ?? { width: 1280, height: 800 });
  await register(page, "Shell Layout", `shell-${Date.now()}@example.com`);
}

/** The metrics every size must satisfy. */
async function shellMetrics(page: Page) {
  return page.evaluate(() => {
    const shell = document.querySelector(".app-shell");
    const sidebar = document.querySelector(".sidebar");
    const main = document.querySelector("main.page");
    if (!shell || !sidebar || !main) {
      throw new Error("The app shell, sidebar or main region is missing.");
    }
    const shellBox = shell.getBoundingClientRect();
    const sidebarBox = sidebar.getBoundingClientRect();
    const doc = document.documentElement;
    return {
      shellWidth: shellBox.width,
      shellHeight: shellBox.height,
      sidebarHeight: sidebarBox.height,
      viewportWidth: doc.clientWidth,
      viewportHeight: doc.clientHeight,
      documentScrollsHorizontally: doc.scrollWidth > doc.clientWidth,
      documentScrollsVertically: doc.scrollHeight > doc.clientHeight,
      mainOverflowY: getComputedStyle(main).overflowY,
      mainScrolls: main.scrollHeight > main.clientHeight,
      bodyOverflowY: getComputedStyle(document.body).overflowY,
    };
  });
}

test("the app shell fills the viewport at every size", async ({ page }) => {
  await signIn(page);

  for (const size of SIZES) {
    await page.setViewportSize(size);
    await page.goto(`${WEB}/results`);
    await expect(page.locator("h1")).toBeVisible();

    const metrics = await shellMetrics(page);

    // The shell is exactly the window: no dead band, no clipped row.
    expect(Math.abs(metrics.shellWidth - metrics.viewportWidth), `${size.width}: shell width`).toBeLessThanOrEqual(1);
    expect(Math.abs(metrics.shellHeight - metrics.viewportHeight), `${size.width}: shell height`).toBeLessThanOrEqual(1);

    // Nothing scrolls sideways at any width.
    expect(metrics.documentScrollsHorizontally, `${size.width}: horizontal overflow`).toBe(false);

    // The document never scrolls; the main region is the scroll container.
    expect(metrics.documentScrollsVertically, `${size.width}: document scroll`).toBe(false);
    expect(metrics.mainOverflowY, `${size.width}: main overflow`).toBe("auto");

    // On a phone the Results page is taller than the window, so the main region
    // must be the thing that scrolls — and the document must not.
    if (size.width === 375) {
      expect(metrics.mainScrolls, `${size.width}: main scrolls`).toBe(true);
      const scrolled = await page.evaluate(() => {
        const main = document.querySelector("main.page");
        if (!main) throw new Error("The main region is missing.");
        main.scrollTop = 240;
        return {
          main: main.scrollTop,
          document: document.documentElement.scrollTop,
          body: document.body.scrollTop,
        };
      });
      expect(scrolled.main, `${size.width}: main actually scrolled`).toBeGreaterThan(0);
      expect(scrolled.document, `${size.width}: document stayed put`).toBe(0);
      expect(scrolled.body, `${size.width}: body stayed put`).toBe(0);
    }

    if (size.width > 800) {
      // The sidebar runs the full height of the window, not of its content.
      expect(
        Math.abs(metrics.sidebarHeight - metrics.viewportHeight),
        `${size.width}: sidebar height`,
      ).toBeLessThanOrEqual(1);
    }
  }

  // Test Chat: whatever the page offers sits inside the window unscrolled.
  for (const size of SIZES) {
    await page.setViewportSize(size);
    await page.goto(`${WEB}/test-chat`);
    await expect(page.getByRole("heading", { name: "Test Chat" })).toBeVisible();
    const placed = await page.evaluate(() => {
      const heading = document.querySelector("h1");
      const main = document.querySelector("main.page");
      if (!heading || !main) throw new Error("Test Chat did not render inside the main region.");
      const box = heading.getBoundingClientRect();
      return {
        scrollTop: main.scrollTop,
        top: box.top,
        left: box.left,
        right: box.right,
        viewportWidth: document.documentElement.clientWidth,
        viewportHeight: document.documentElement.clientHeight,
      };
    });
    expect(placed.scrollTop, `${size.width}: Test Chat starts unscrolled`).toBe(0);
    expect(placed.left, `${size.width}: Test Chat heading left edge`).toBeGreaterThanOrEqual(0);
    expect(placed.right, `${size.width}: Test Chat heading right edge`).toBeLessThanOrEqual(
      placed.viewportWidth,
    );
    expect(placed.top, `${size.width}: Test Chat heading top edge`).toBeGreaterThanOrEqual(0);
    expect(placed.top, `${size.width}: Test Chat heading inside the window`).toBeLessThan(
      placed.viewportHeight,
    );
  }
});

async function shoot(
  page: Page,
  name: string,
  size: { width: number; height: number },
  theme: "dark" | "light",
): Promise<void> {
  await page.setViewportSize(size);
  // A frame, so the resize has been painted before the pixels are read.
  await page.waitForTimeout(120);
  await page.screenshot({
    path: path.join(SCREENS, `${PREFIX}-${name}-${size.width}x${size.height}-${theme}.png`),
  });
}

test("captures the shell at four viewports", async ({ page }) => {
  await page.setViewportSize(SIZES[0] ?? { width: 1280, height: 800 });
  await page.goto(`${WEB}/login`);
  await expect(page.locator("#login-email")).toBeVisible();

  for (const size of SIZES) {
    await shoot(page, "login", size, "dark");
  }

  await signIn(page);

  for (const target of PAGES) {
    for (const size of SIZES) {
      await page.setViewportSize(size);
      await page.goto(`${WEB}${target.url}`);
      await expect(page.locator("h1")).toBeVisible();
      await shoot(page, target.name, size, "dark");
    }
  }

  // The light theme gets one page at every size: the same shell, other colours.
  await page.setViewportSize(SIZES[0] ?? { width: 1280, height: 800 });
  await page.goto(`${WEB}/`);
  await page.getByRole("button", { name: /switch to light theme/i }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");

  for (const size of SIZES) {
    await page.goto(`${WEB}/`);
    await shoot(page, "new-test", size, "light");
  }
});

/**
 * `body { overflow: hidden }` must never be the reason something is unreachable:
 * a short window has to scroll, and a zoomed-in window has to keep working.
 */
test("short and zoomed-in windows keep every control reachable", async ({ page }) => {
  // (a) A 500px-tall window (a laptop with the bookmarks bar open, a phone with
  // the keyboard up): the login container scrolls and the submit button is
  // inside the window once scrolled to.
  for (const size of [
    { width: 1280, height: 500 },
    { width: 375, height: 500 },
  ]) {
    await page.setViewportSize(size);
    await page.goto(`${WEB}/login`);
    await expect(page.locator("#login-email")).toBeVisible();

    const container = await page.evaluate(() => {
      const auth = document.querySelector(".auth-page");
      if (!auth) throw new Error("The auth page container is missing.");
      return {
        overflowY: getComputedStyle(auth).overflowY,
        documentScrolls:
          document.documentElement.scrollHeight > document.documentElement.clientHeight,
      };
    });
    expect(container.overflowY, `${size.width}x${size.height}: auth page scrolls`).toBe("auto");
    expect(container.documentScrolls, `${size.width}x${size.height}: document stays put`).toBe(
      false,
    );

    const submit = page.locator('button[type="submit"]');
    await submit.scrollIntoViewIfNeeded();
    const placed = await submit.evaluate((button) => {
      const box = button.getBoundingClientRect();
      return {
        top: box.top,
        bottom: box.bottom,
        viewportHeight: document.documentElement.clientHeight,
      };
    });
    expect(placed.top, `${size.width}x${size.height}: submit top edge`).toBeGreaterThanOrEqual(0);
    expect(placed.bottom, `${size.width}x${size.height}: submit is inside the window`).toBeLessThanOrEqual(
      placed.viewportHeight + 1,
    );

    await page.screenshot({
      path: path.join(SCREENS, `${PREFIX}-login-${size.width}x${size.height}-dark.png`),
    });
  }

  // (b) 640x400 is 1280x800 at 200% zoom: the main region scrolls, the nav still works.
  await page.setViewportSize({ width: 640, height: 400 });
  await register(page, "Zoom Layout", `zoom-${Date.now()}@example.com`);
  await page.goto(`${WEB}/results`);
  await expect(page.locator("h1")).toBeVisible();

  const zoomed = await shellMetrics(page);
  expect(Math.abs(zoomed.shellWidth - zoomed.viewportWidth), "zoom: shell width").toBeLessThanOrEqual(
    1,
  );
  expect(Math.abs(zoomed.shellHeight - zoomed.viewportHeight), "zoom: shell height").toBeLessThanOrEqual(
    1,
  );
  expect(zoomed.documentScrollsVertically, "zoom: document scroll").toBe(false);
  expect(zoomed.documentScrollsHorizontally, "zoom: horizontal overflow").toBe(false);
  expect(zoomed.mainOverflowY, "zoom: main overflow").toBe("auto");
  expect(zoomed.mainScrolls, "zoom: main scrolls").toBe(true);

  await page.screenshot({
    path: path.join(SCREENS, `${PREFIX}-results-640x400-dark.png`),
  });

  // The nav strip is still usable at that size, not just visible.
  await page.getByRole("link", { name: "Settings" }).click();
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
});

/**
 * The light theme's verdict green was darkened to reach AA contrast; this proves
 * the new value reaches a real GO on the Results page, not just the stylesheet.
 */
test("keeps the GO colour readable on Results in the light theme", async ({ page }) => {
  test.setTimeout(240_000);

  await page.setViewportSize({ width: 1440, height: 900 });
  await register(page, "Light Verdict", `light-verdict-${Date.now()}@example.com`);
  await page.goto(`${WEB}/`);
  await expect(page.getByTestId("try-demo")).toBeVisible({ timeout: 20_000 });
  await page.click('[data-testid="try-demo"]');
  await expect(page.getByTestId("demo-good-verdict")).toHaveText("Go", { timeout: 180_000 });

  await page.goto(`${WEB}/results`);
  const verdict = page.locator('[data-testid="run-history-verdict"]').filter({ hasText: "Go" }).first();
  await expect(verdict).toBeVisible({ timeout: 30_000 });

  await page.getByRole("button", { name: /switch to light theme/i }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");

  // #0b7a22: the light theme's GO, measured at 5.50:1 on the page colour.
  await expect(verdict).toHaveCSS("color", "rgb(11, 122, 34)");
  await page.screenshot({
    path: path.join(SCREENS, `${PREFIX}-results-light-1440x900.png`),
  });
});

/**
 * The desktop rail: one toggle, stored in localStorage, read before the first
 * paint, and the shell still fills the window because the grid only trades
 * columns.
 */
test("the sidebar collapses to a rail, survives a reload and still navigates", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await register(page, "Sidebar Rail", `rail-${Date.now()}@example.com`);
  await page.goto(`${WEB}/`);
  await expect(page.getByRole("heading", { name: "New Test" })).toBeVisible();

  const toggle = page.getByTestId("sidebar-toggle");
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(toggle).toHaveAccessibleName("Collapse sidebar");
  await page.screenshot({
    path: path.join(SCREENS, `${PREFIX}-sidebar-default-1280x800-dark.png`),
  });

  await toggle.click();

  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(toggle).toHaveAccessibleName("Expand sidebar");
  await expect(page.getByTestId("sidebar-rail")).toBeVisible();

  const rail = await page.evaluate(() => {
    const sidebar = document.querySelector(".sidebar");
    const shell = document.querySelector(".app-shell");
    if (!sidebar || !shell) throw new Error("The shell is missing.");
    const doc = document.documentElement;
    return {
      sidebarWidth: sidebar.getBoundingClientRect().width,
      shellWidth: shell.getBoundingClientRect().width,
      shellHeight: shell.getBoundingClientRect().height,
      viewportWidth: doc.clientWidth,
      viewportHeight: doc.clientHeight,
      horizontal: doc.scrollWidth > doc.clientWidth,
      stored: window.localStorage.getItem("greenlit-sidebar-collapsed"),
    };
  });
  // 56px of rail, and the shell still exactly fills the window.
  expect(rail.sidebarWidth).toBeLessThanOrEqual(64);
  expect(Math.abs(rail.shellWidth - rail.viewportWidth)).toBeLessThanOrEqual(1);
  expect(Math.abs(rail.shellHeight - rail.viewportHeight)).toBeLessThanOrEqual(1);
  expect(rail.horizontal, "rail: horizontal overflow").toBe(false);
  expect(rail.stored).toBe("true");

  await page.screenshot({
    path: path.join(SCREENS, `${PREFIX}-sidebar-collapsed-1280x800-dark.png`),
  });

  // A reload keeps the rail shut: the stored value is read before the first paint.
  await page.reload();
  await expect(page.getByTestId("sidebar-toggle")).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByTestId("sidebar-rail")).toBeVisible();

  // The label is still the link's accessible name while the rail is folded.
  await page.getByRole("link", { name: "Results", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Results" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Results", exact: true })).toHaveClass(
    "sidebar__link sidebar__link--active",
  );

  await page.getByRole("button", { name: /switch to light theme/i }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.screenshot({
    path: path.join(SCREENS, `${PREFIX}-sidebar-collapsed-1280x800-light.png`),
  });

  await page.getByTestId("sidebar-toggle").click();
  await expect(page.getByTestId("sidebar-toggle")).toHaveAttribute("aria-expanded", "true");
  await page.screenshot({
    path: path.join(SCREENS, `${PREFIX}-sidebar-expanded-1280x800-light.png`),
  });
});
