/** Typed client for the read-only built-in safety sets (spec 8.3). */

import { apiRequest } from "./api";

export type SafetySetKind = "attacks" | "safe_prompts";
export type SafetySeverity = "critical" | "standard";

export interface SafetySet {
  id: string;
  name: string;
  description: string;
  kind: SafetySetKind;
  case_count: number;
  critical_count: number;
  severity: SafetySeverity;
}

export interface SafetyItem {
  id: string;
  category: string;
  severity: SafetySeverity;
  prompt: string;
  expected: string;
}

export interface SafetySummary {
  attack_count: number;
  safe_prompt_count: number;
  category_count: number;
  critical_count: number;
}

export interface SafetyCatalogue {
  version: string;
  safe_prompt_version: string;
  /** The synthetic marker the attacks try to make the app repeat. */
  marker: string;
  marker_note: string;
  canary_rule: string;
  summary: SafetySummary;
  sets: SafetySet[];
  items: SafetyItem[];
}

export function getSafetyCatalogue(): Promise<SafetyCatalogue> {
  return apiRequest("/api/v1/safety/sets");
}
