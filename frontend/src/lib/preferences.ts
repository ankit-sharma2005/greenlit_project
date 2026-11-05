import { apiRequest } from "./api";
import type { Theme } from "./theme";

export interface Preferences {
  theme: Theme;
}

export function fetchPreferences(): Promise<Preferences> {
  return apiRequest<Preferences>("/api/v1/auth/me/preferences");
}

/** The API replaces the whole preference document, so a change sends every key it owns. */
export function updatePreferences(theme: Theme): Promise<Preferences> {
  return apiRequest<Preferences>("/api/v1/auth/me/preferences", {
    method: "PATCH",
    body: { theme },
  });
}
