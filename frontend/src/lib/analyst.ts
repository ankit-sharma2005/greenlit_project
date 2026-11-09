/** Typed client for the analyst endpoints (PART 2). */

import { apiRequest } from "./api";

export interface ExplanationPreview {
  input: string;
  input_hash: string;
  provider_id: string;
  provider_name: string;
  model: string;
  prompt_version: string;
  provider_is_local: boolean;
}

export type ExplanationStatus = "ok" | "rejected" | "error" | "none";

export interface Explanation {
  status: ExplanationStatus;
  text: string;
  message: string;
  model: string | null;
  provider_name: string | null;
  prompt_version: string | null;
  created_at: string | null;
  input_hash: string | null;
}

/** Exactly what would be sent, so the panel can show it before anything leaves. */
export function previewExplanation(runId: string): Promise<ExplanationPreview> {
  return apiRequest(`/api/v1/runs/${runId}/explain/preview`, { method: "POST" });
}

/** One analyst call per click; the server reuses its stored row for the same input. */
export function explainRun(runId: string, confirmRemote = false): Promise<Explanation> {
  return apiRequest(`/api/v1/runs/${runId}/explain`, {
    method: "POST",
    body: { confirm_remote: confirmRemote },
  });
}

/** Never calls a model: returns the stored explanation or `status: "none"`. */
export function getExplanation(runId: string): Promise<Explanation> {
  return apiRequest(`/api/v1/runs/${runId}/explanation`);
}
