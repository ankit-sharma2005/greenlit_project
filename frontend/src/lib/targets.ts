/** Typed client for the first-contact check before a remote full run (STEP 2). */

import { apiRequest } from "./api";

export interface TargetCheckRequest {
  target: string;
  dataset_version_id?: string;
  method?: string;
  body_template?: string;
  headers?: Record<string, string>;
  /** cURL-imported headers and cookies, encrypted by the server. */
  headers_secret?: string;
  header_names?: string[];
  answer_path?: string;
  context_path?: string;
  timeout_seconds?: number;
  allow_private_targets?: boolean;
  permission_confirmed?: boolean;
  permission_reference?: string;
  safety_attacks_confirmed?: boolean;
  max_concurrency?: number;
  min_delay_ms?: number;
  max_retries?: number;
  response_format?: "json" | "sse" | "ndjson" | "text";
  stream_content_path?: string;
}

export interface TargetCheckError {
  kind: string;
  status: number | null;
  target: string;
  snippet: string;
  message: string;
  summary: string;
}

/** One harmless request: what it sent, what came back, and what was read. */
export interface TargetCheck {
  check_id: string;
  expires_at: string;
  accepted: boolean;
  request: {
    method: string;
    url: string;
    headers: Record<string, string>;
    body: string;
    input: string;
  };
  status: number | null;
  latency_ms: number | null;
  answer: string;
  answer_truncated: boolean;
  /** True only for readable, non-HTML text: the only thing a person may accept. */
  extraction_ok: boolean;
  mapping_path: string | null;
  hint: string | null;
  error: TargetCheckError | null;
}

export function checkTarget(body: TargetCheckRequest): Promise<TargetCheck> {
  return apiRequest("/api/v1/targets/check", { method: "POST", body, timeoutMs: 90_000 });
}

export function acceptTargetCheck(checkId: string): Promise<TargetCheck> {
  return apiRequest(`/api/v1/targets/check/${checkId}/accept`, { method: "POST" });
}
