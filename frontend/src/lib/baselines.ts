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
