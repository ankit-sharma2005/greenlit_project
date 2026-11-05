import { afterEach, describe, expect, it, vi } from "vitest";

import {
  DEFAULT_THEME,
  THEME_STORAGE_KEY,
  cacheTheme,
  clearCachedTheme,
  isTheme,
  readCachedTheme,
  resolveTheme,
} from "./theme";

function stubSystemPrefersDark(dark: boolean): void {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: dark,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

afterEach(() => {
  window.localStorage.clear();
  vi.unstubAllGlobals();
});

describe("theme helpers", () => {
  it("defaults to dark and ignores a value it does not recognise", () => {
    expect(DEFAULT_THEME).toBe("dark");
    expect(readCachedTheme()).toBe("dark");

    window.localStorage.setItem(THEME_STORAGE_KEY, "neon");
    expect(readCachedTheme()).toBe("dark");
    expect(isTheme("neon")).toBe(false);
  });

  it("caches and clears the choice", () => {
    cacheTheme("light");
    expect(readCachedTheme()).toBe("light");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");

    clearCachedTheme();
    expect(readCachedTheme()).toBe("dark");
  });

  it("resolves system against the OS setting and leaves explicit choices alone", () => {
    stubSystemPrefersDark(true);
    expect(resolveTheme("system")).toBe("dark");
    expect(resolveTheme("light")).toBe("light");

    stubSystemPrefersDark(false);
    expect(resolveTheme("system")).toBe("light");
  });

  it("falls back to dark when matchMedia is unavailable", () => {
    vi.stubGlobal("matchMedia", undefined);

    expect(resolveTheme("system")).toBe("dark");
  });
});
