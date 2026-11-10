import { useEffect, useState } from "react";

import { fetchPreferences, type Preferences } from "./preferences";

/**
 * The signed-in account's preferences, or null until they arrive.
 *
 * Screens that only need a display choice (a time zone, the answer length) read
 * it here instead of growing their own fetch; a failure leaves null, so the
 * screen keeps its documented default rather than showing an error for a detail.
 */
export function useAccountPreferences(): Preferences | null {
  const [preferences, setPreferences] = useState<Preferences | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchPreferences()
      .then((value) => {
        if (!cancelled) setPreferences(value);
      })
      .catch(() => {
        /* no stored preference is the same as the default, never a broken screen */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return preferences;
}
