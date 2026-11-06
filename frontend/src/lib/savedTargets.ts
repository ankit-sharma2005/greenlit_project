/** Typed client for saved targets (Settings → Connectors). */

import { apiRequest } from "./api";

export type ResponseFormat = "json" | "sse" | "ndjson" | "text";

/** A saved target: where an app lives and how GreenLit reads its answer. */
export interface SavedTarget {
  id: string;
  name: string;
  connector_type: string;
  url: string;
  method: string;
  body_template: string | null;
  /** Header names only: a saved target never keeps a header value. */
  header_names: string[];
  answer_path: string | null;
  context_path: string | null;
  stream_content_path: string | null;
  response_format: ResponseFormat;
  timeout_seconds: number;
  max_concurrency: number;
  min_delay_ms: number;
  max_retries: number;
  allow_private_targets: boolean;
  created_at: string;
  updated_at: string;
}

export interface SavedTargetPayload {
  name: string;
  url: string;
  method?: string;
  body_template?: string | null;
  answer_path?: string | null;
  context_path?: string | null;
  stream_content_path?: string | null;
  response_format?: ResponseFormat;
  timeout_seconds?: number;
  max_concurrency?: number;
  min_delay_ms?: number;
  max_retries?: number;
  allow_private_targets?: boolean;
}

export interface SavedTargetList {
  items: SavedTarget[];
  total: number;
}

export function listSavedTargets(): Promise<SavedTargetList> {
  return apiRequest("/api/v1/saved-targets");
}

export function createSavedTarget(body: SavedTargetPayload): Promise<SavedTarget> {
  return apiRequest("/api/v1/saved-targets", { method: "POST", body });
}

export function updateSavedTarget(id: string, body: SavedTargetPayload): Promise<SavedTarget> {
  return apiRequest(`/api/v1/saved-targets/${id}`, { method: "PATCH", body });
}

export function deleteSavedTarget(id: string): Promise<void> {
  return apiRequest(`/api/v1/saved-targets/${id}`, { method: "DELETE" });
}
