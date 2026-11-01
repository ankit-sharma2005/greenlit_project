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

export interface RunJudge {
  model: string | null;
  provider_name: string | null;
  profile_name: string | null;
  rubric_version: string | null;
  prompt_template_hash: string | null;
  temperature: number | null;
  max_tokens: number | null;
  /** The profile's per-run cap; null means every case was judged. */
  max_cases: number | null;
  /** Answerable cases the run had, and how many the cap left out. */
  case_total: number;
  capped_items: number;
  graded_items: number;
  unavailable_items: number;
  low_confidence_items: number;
}

export type RegressionStatus = "PASS" | "WARN" | "BLOCK";

export interface RegressionMetric {
  name: string;
  baseline: number | null;
  current: number | null;
  delta: number | null;
  passed_before: boolean;
  passed_now: boolean;
  hard_gate: boolean;
  regressed: boolean;
}

export interface RegressedCase {
  row_index: number;
  input: string;
}

/** How a finished run compares with its dataset version's baseline (spec 8.5). */
export interface RunRegression {
  status: RegressionStatus;
  reason: string;
  baseline_run_id: string | null;
  baseline_run_name: string | null;
  metric_tolerance: number;
  case_tolerance: number;
  metric_deltas: RegressionMetric[];
  regressed_metrics: string[];
  regressed_cases: RegressedCase[];
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
  /** Which judge scored the answers; null when the run was not judged. */
  judge: RunJudge | null;
  judge_skipped_reason: string | null;
  /** The stored baseline comparison; null when no baseline existed. */
  regression?: RunRegression | null;
  /** True when this run *is* the dataset version's baseline. */
  is_baseline?: boolean;
  /** Speed, reliability and token use; null on runs that predate the block. */
  operations?: RunOperations | null;
}

/**
 * Every rate and latency is null when it could not be measured, so the UI can
 * say "not measured" instead of showing a misleading zero.
 */
export interface RunOperations {
  items_total: number;
  items_attempted: number;
  items_failed: number;
  items_cancelled: number;
  latency_samples: number;
  latency_p50_ms: number | null;
  latency_p95_ms: number | null;
  error_rate: number | null;
  timeout_rate: number | null;
  items_timed_out: number;
  tokens_in_total: number | null;
  tokens_out_total: number | null;
  price_per_1k_tokens_in: number | null;
  price_per_1k_tokens_out: number | null;
  cost_configured: boolean;
  cost_estimate: number | null;
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
  max_concurrency?: number;
  min_delay_ms?: number;
  max_retries?: number;
  provider_id?: string;
  model?: string;
  system_prompt?: string;
  temperature?: number;
  judge_profile_id?: string;
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
  max_concurrency?: number;
  min_delay_ms?: number;
  max_retries?: number;
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

export interface RunListResponse {
  items: Run[];
  total: number;
  limit: number;
  offset: number;
}

export function listRuns(
  options: { limit?: number; offset?: number } = {},
): Promise<RunListResponse> {
  const limit = options.limit ?? 20;
  const offset = options.offset ?? 0;
  return apiRequest(`/api/v1/runs?limit=${limit}&offset=${offset}`);
}

export function getRunProgress(id: string): Promise<RunProgress> {
  return apiRequest(`/api/v1/runs/${id}/progress`);
}

export function cancelRun(id: string): Promise<Run> {
  return apiRequest(`/api/v1/runs/${id}/cancel`, { method: "POST" });
}
