/**
 * Theme preference helpers.
 *
 * The choice ("dark", "light" or "system") is what the user picks and what the
 * API stores. What the browser paints is the *resolved* theme, because
 * "system" is only known locally. The resolved value is cached in localStorage
 * so the first paint after a reload is already right; the account remains the
 * source of truth so two accounts on one browser do not share it.
 */

export type Theme = "dark" | "light" | "system";
export type ResolvedTheme = "dark" | "light";

export const DEFAULT_THEME: Theme = "dark";
export const THEME_STORAGE_KEY = "greenlit-theme";

const THEMES: Theme[] = ["dark", "light", "system"];

export interface ThemeOption {
  value: Theme;
  label: string;
  detail: string;
}

export const THEME_OPTIONS: ThemeOption[] = [
  { value: "dark", label: "Dark", detail: "The GreenLit default: light text on a dark surface." },
  { value: "light", label: "Light", detail: "Dark text on a light surface, for a bright room." },
  {
    value: "system",
    label: "System default",
    detail: "Follow the operating system's light or dark setting, including later changes.",
  },
];

export function isTheme(value: unknown): value is Theme {
  return typeof value === "string" && (THEMES as string[]).includes(value);
}

/** The cached choice, used before the API answers so a reload does not flash. */
export function readCachedTheme(): Theme {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isTheme(stored) ? stored : DEFAULT_THEME;
  } catch {
    // Storage can be unavailable (private mode); the default still applies.
    return DEFAULT_THEME;
  }
}

export function cacheTheme(theme: Theme): void {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // A missing cache only costs one flash of the default theme.
  }
}

export function clearCachedTheme(): void {
  try {
    window.localStorage.removeItem(THEME_STORAGE_KEY);
  } catch {
    // Nothing to clear when storage is unavailable.
  }
}

function prefersDark(): boolean {
  // No media query support means no way to ask: keep the app's own default.
  if (typeof window.matchMedia !== "function") return true;
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export function resolveTheme(theme: Theme): ResolvedTheme {
  if (theme === "system") {
    return prefersDark() ? "dark" : "light";
  }
  return theme;
}

export function applyTheme(resolved: ResolvedTheme): void {
  document.documentElement.dataset.theme = resolved;
}
