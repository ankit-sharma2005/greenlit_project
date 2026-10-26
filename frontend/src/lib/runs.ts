/** Typed client for the run endpoints (M6). A run always executes in the worker. */

import { apiRequest } from "./api";
import type { FailedCase, MetricRow, Verdict } from "./evaluations";

export type RunState = "queued" | "running" | "cancelling" | "cancelled" | "failed" | "completed";

export const TERMINAL_STATES: readonly RunState[] = ["cancelled", "failed", "completed"];

export function isTerminal(state: RunState): boolean {
  return TERMINAL_STATES.includes(state);
}

export type TestType = "quality" | "safety" | "operations";

export interface RunProgress {
  items_done: number;
  items_total: number;
  items_failed: number;
  items_cancelled: number;
  stage: string;
  started_at: string | null;
  updated_at: string | null;
  elapsed_seconds: number | null;
}

export interface Run {
  id: string;
  name: string;
  entry_point: string;
  state: RunState;
  verdict: Verdict | null;
  score: number | null;
  verdict_reason: string | null;
  is_partial: boolean;
  criteria_profile: string;
  test_types: string[];
  dataset_id: string | null;
  dataset_version_id: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  progress: RunProgress;
  metrics: MetricRow[];
  failed_cases: FailedCase[];
}

export interface RunCreateRequest {
  name?: string;
  entry_point: "http_endpoint" | "prompt_app" | "upload_outputs";
  target?: string;
  test_types?: TestType[];
  dataset_id?: string;
  dataset_version_id?: string;
  criteria_profile?: string;
  method?: string;
  body_template?: string;
  headers?: Record<string, string>;
  answer_path?: string;
  context_path?: string;
  timeout_seconds?: number;
  allow_private_targets?: boolean;
  provider_id?: string;
  model?: string;
  system_prompt?: string;
  temperature?: number;
}

export interface QuickTestRequest {
  entry_point?: "http_endpoint" | "prompt_app" | "upload_outputs";
  target: string;
  tests?: TestType[];
  dataset_id?: string;
  csv?: string;
  generate?: number;
  provider_id?: string;
  model?: string;
  method?: string;
  body_template?: string;
  headers?: Record<string, string>;
  answer_path?: string;
  context_path?: string;
  timeout_seconds?: number;
  allow_private_targets?: boolean;
  name?: string;
}

export interface QuickTestResponse {
  run: Run;
  dataset_id: string;
  dataset_version_id: string;
  generated: boolean;
}

export function startRun(body: RunCreateRequest): Promise<Run> {
  return apiRequest("/api/v1/runs", { method: "POST", body });
}

export function quickTest(body: QuickTestRequest): Promise<QuickTestResponse> {
  return apiRequest("/api/v1/quick-test", { method: "POST", body, timeoutMs: 120_000 });
}

export function getRun(id: string): Promise<Run> {
  return apiRequest(`/api/v1/runs/${id}`);
}

export function getRunProgress(id: string): Promise<RunProgress> {
  return apiRequest(`/api/v1/runs/${id}/progress`);
}

export function cancelRun(id: string): Promise<Run> {
  return apiRequest(`/api/v1/runs/${id}/cancel`, { method: "POST" });
}
