import { apiRequest } from "./api";
import type { Theme } from "./theme";

/** One role's chosen provider and model; the provider's key is never part of it. */
export interface ModelChoice {
  provider_id: string;
  model: string;
}

export type ModelRole = "judge" | "target" | "generator" | "analyst";

export interface Preferences {
  theme: Theme;
  /** Roles the account has not chosen yet are absent, not null. */
  judge?: ModelChoice | null;
  target?: ModelChoice | null;
  generator?: ModelChoice | null;
  analyst?: ModelChoice | null;
}

export function fetchPreferences(): Promise<Preferences> {
  return apiRequest<Preferences>("/api/v1/auth/me/preferences");
}

/**
 * The API replaces the whole preference document, so a change sends every key it owns.
 * `theme` is required; a role that is not passed keeps the value already stored.
 */
export function updatePreferences(
  theme: Theme,
  models: Partial<Record<ModelRole, ModelChoice>> = {},
): Promise<Preferences> {
  return apiRequest<Preferences>("/api/v1/auth/me/preferences", {
    method: "PATCH",
    body: { theme, ...models },
  });
}
