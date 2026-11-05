import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { useAuth } from "../auth/authContext";
import { ApiError } from "../lib/api";
import { fetchPreferences, updatePreferences } from "../lib/preferences";
import {
  DEFAULT_THEME,
  applyTheme,
  cacheTheme,
  clearCachedTheme,
  readCachedTheme,
  resolveTheme,
  type ResolvedTheme,
  type Theme,
} from "../lib/theme";
import { ThemeContext, type ThemeContextValue } from "./themeContext";

/**
 * Owns the theme for the whole app.
 *
 * Three things have to agree: the topbar toggle, Settings → Preferences, and
 * the attribute the CSS reads. One provider is what keeps them in sync instead
 * of two components each holding a copy. The account is the source of truth —
 * the choice is loaded when a user is signed in and cleared on sign-out, so the
 * next person on this browser does not inherit it.
 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const userId = user?.id ?? null;
  const [theme, setThemeState] = useState<Theme>(readCachedTheme);
  const [resolved, setResolved] = useState<ResolvedTheme>(() => resolveTheme(readCachedTheme()));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const previousUserId = useRef<string | null>(null);
  // A choice made before the account's stored value arrives must win over it.
  const touched = useRef(false);

  // Apply immediately, and keep following the OS while "system" is selected.
  useEffect(() => {
    const apply = () => {
      const next = resolveTheme(theme);
      applyTheme(next);
      setResolved(next);
    };
    apply();

    if (theme !== "system" || typeof window.matchMedia !== "function") {
      return;
    }
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [theme]);

  // Load the account's own choice; drop it when the session ends.
  useEffect(() => {
    let cancelled = false;
    const wasSignedIn = previousUserId.current !== null;
    previousUserId.current = userId;

    if (!userId) {
      if (wasSignedIn) {
        touched.current = false;
        setThemeState(DEFAULT_THEME);
        clearCachedTheme();
      }
      return;
    }

    fetchPreferences()
      .then((preferences) => {
        if (cancelled || touched.current) return;
        setThemeState(preferences.theme);
        cacheTheme(preferences.theme);
      })
      .catch(() => {
        // The cached theme stays; saving reports its own failure on the panel.
      });
    return () => {
      cancelled = true;
    };
  }, [userId]);

  const persist = useCallback(
    async (next: Theme): Promise<boolean> => {
      touched.current = true;
      setThemeState(next);
      cacheTheme(next);
      setError(null);

      if (!userId) {
        // No account to store it on; the value still applies to this session.
        return true;
      }

      setSaving(true);
      try {
        await updatePreferences(next);
        return true;
      } catch (caught) {
        setError(
          caught instanceof ApiError
            ? caught.message
            : "Could not save your preference. Check your connection and try again.",
        );
        return false;
      } finally {
        setSaving(false);
      }
    },
    [userId],
  );

  const resetTheme = useCallback(() => persist(DEFAULT_THEME), [persist]);

  const value = useMemo<ThemeContextValue>(
    () => ({ theme, resolved, saving, error, setTheme: persist, resetTheme }),
    [theme, resolved, saving, error, persist, resetTheme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}
