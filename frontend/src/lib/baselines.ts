/** Typed client for baselines and regression (spec 8.5). One per dataset version. */

import { apiRequest } from "./api";

export interface Baseline {
  run_id: string;
  run_name: string | null;
  dataset_id: string | null;
  dataset_version_id: string | null;
  metric_tolerance: number;
  case_tolerance: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface BaselineCreate {
  metric_tolerance?: number;
  case_tolerance?: number;
}

/** The baseline for this run's dataset version, or null when none is set. */
export function getBaseline(runId: string): Promise<Baseline | null> {
  return apiRequest(`/api/v1/runs/${runId}/baseline`);
}

export function setBaseline(runId: string, body: BaselineCreate = {}): Promise<Baseline> {
  return apiRequest(`/api/v1/runs/${runId}/baseline`, { method: "POST", body });
}

export function clearBaseline(runId: string): Promise<void> {
  return apiRequest(`/api/v1/runs/${runId}/baseline`, { method: "DELETE" });
}

export interface CompareMetric {
  name: string;
  status: "measured" | "not measured";
  baseline: number | null;
  current: number | null;
  delta: number | null;
  passed_before: boolean | null;
  passed_now: boolean | null;
  hard_gate: boolean;
}

export interface CompareCaseRef {
  row_index: number;
  input: string;
}

export interface CompareLatency {
  p50: number | null;
  p95: number | null;
  samples?: number;
}

/** One run against a baseline (or another run): the extra detail on top of PASS/WARN/BLOCK. */
export interface CompareDetail {
  comparable: boolean;
  reasons: string[];
  baseline_run_id: string;
  baseline_run_name: string | null;
  current_run_id: string;
  current_run_name: string;
  tolerance: number;
  deterministic_target: boolean;
  noise_caution: string | null;
  verdict: { baseline: string | null; current: string | null; direction: string };
  verdict_changed: boolean;
  score: { baseline: number | null; current: number | null; delta: number | null };
  /** Null when not comparable: no deltas are given for runs that cannot be compared. */
  classification: "regressed" | "improved" | "unchanged" | null;
  classification_reason: string | null;
  existing_status: string | null;
  metrics: CompareMetric[];
  hard_gates: { newly_failed: string[]; newly_passed: string[] };
  latency: {
    baseline: CompareLatency | null;
    current: CompareLatency | null;
    delta: { p50: number | null; p95: number | null } | null;
  };
  cases: {
    pass_to_fail: CompareCaseRef[];
    fail_to_pass: CompareCaseRef[];
    new_errors: CompareCaseRef[];
    only_in_baseline: CompareCaseRef[];
    only_in_current: CompareCaseRef[];
  };
}

/** The detail for this run against its baseline, or another of the owner's runs. */
export function getCompare(runId: string, against = "baseline", tolerance?: number): Promise<CompareDetail> {
  const params = new URLSearchParams({ against });
  if (tolerance !== undefined) params.set("tolerance", String(tolerance));
  return apiRequest(`/api/v1/runs/${runId}/compare?${params.toString()}`);
}
