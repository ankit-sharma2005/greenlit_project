/** Typed client for judge profiles (M7). A profile is which model grades a run. */

import { apiRequest } from "./api";

export interface JudgeProfile {
  id: string;
  name: string;
  provider_id: string | null;
  provider_name: string | null;
  model: string | null;
  rubric_version: string;
  temperature: number;
  max_tokens: number;
  is_selected: boolean;
  created_at: string;
  updated_at: string;
  /** Self-grading warnings for the profile's current provider/model. */
  warnings: string[];
}

export interface JudgeProfileCreate {
  name: string;
  provider_id?: string | null;
  model?: string | null;
  max_tokens?: number;
}

export interface JudgeProfileList {
  items: JudgeProfile[];
  total: number;
  selected_id: string | null;
}

export function listJudgeProfiles(): Promise<JudgeProfileList> {
  return apiRequest("/api/v1/judge-profiles");
}

export function createJudgeProfile(body: JudgeProfileCreate): Promise<JudgeProfile> {
  return apiRequest("/api/v1/judge-profiles", { method: "POST", body });
}

export function selectJudgeProfile(id: string): Promise<JudgeProfile> {
  return apiRequest(`/api/v1/judge-profiles/${id}/select`, { method: "POST" });
}

export function deleteJudgeProfile(id: string): Promise<void> {
  return apiRequest(`/api/v1/judge-profiles/${id}`, { method: "DELETE" });
}
