import { createContext, useContext } from "react";

import type { ResolvedTheme, Theme } from "../lib/theme";

export interface ThemeContextValue {
  /** The saved preference, which may be "system". */
  theme: Theme;
  /** What is painted right now, with "system" resolved. */
  resolved: ResolvedTheme;
  saving: boolean;
  /** The last save failure, in the API's own words. */
  error: string | null;
  /** Apply immediately, then save to the account. Resolves false when the save failed. */
  setTheme: (theme: Theme) => Promise<boolean>;
  resetTheme: () => Promise<boolean>;
}

export const ThemeContext = createContext<ThemeContextValue | null>(null);

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error("useTheme must be used inside <ThemeProvider>");
  }
  return context;
}
