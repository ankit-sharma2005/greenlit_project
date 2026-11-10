import { apiRequest } from "./api";
import type { Theme } from "./theme";

/** One role's chosen provider and model; the provider's key is never part of it. */
export interface ModelChoice {
  provider_id: string;
  model: string;
}

export type ModelRole = "judge" | "target" | "generator" | "analyst";

/** The entry points a New Test form can open on. */
export type DefaultEntryPoint = "http_endpoint" | "prompt_app" | "upload_outputs" | "mcp_server";

export type DefaultTestType = "quality" | "safety" | "operations";

/** The preference document. Keys the account never set are absent, not null. */
export interface Preferences {
  theme: Theme;
  entry_point?: DefaultEntryPoint | null;
  test_types?: DefaultTestType[] | null;
  /** An IANA zone name, e.g. "Europe/Berlin". */
  time_zone?: string | null;
  /** Off truncates long answers in the run view, behind a "Show more" control. */
  show_full_answers?: boolean | null;
  judge?: ModelChoice | null;
  target?: ModelChoice | null;
  generator?: ModelChoice | null;
  analyst?: ModelChoice | null;
}

/** The keys the Preferences panel owns, beyond the theme it shares with the topbar. */
export interface DisplayPreferences {
  entry_point?: DefaultEntryPoint;
  test_types?: DefaultTestType[];
  time_zone?: string;
  show_full_answers?: boolean;
}

export function fetchPreferences(): Promise<Preferences> {
  return apiRequest<Preferences>("/api/v1/auth/me/preferences");
}

/**
 * The API replaces the whole preference document, so a change sends every key it owns.
 * `theme` is required; a role or display key that is not passed keeps the value
 * already stored, which is why each key may be omitted rather than cleared.
 */
export function updatePreferences(
  theme: Theme,
  models: Partial<Record<ModelRole, ModelChoice>> = {},
  display: DisplayPreferences = {},
): Promise<Preferences> {
  return apiRequest<Preferences>("/api/v1/auth/me/preferences", {
    method: "PATCH",
    body: { theme, ...models, ...display },
  });
}
