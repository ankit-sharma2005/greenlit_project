/** Typed client for the read-only criteria overview (spec 8.4). */

import { apiRequest } from "./api";

export type MetricGroup = "quality" | "safety" | "operations";
export type Verdict = "GO" | "REVIEW" | "NO_GO";
export type AppliesWhen = "always" | "safety on" | "judge configured";

export interface Criterion {
  name: string;
  group: MetricGroup;
  weight: number;
  hard_gate: boolean;
  threshold: number;
  gate_threshold: number | null;
  applies: AppliesWhen;
}

export interface DecisionRule {
  rule: number;
  verdict: Verdict;
  text: string;
}

export interface CriteriaTemplate {
  key: string;
  name: string;
  description: string;
  criteria_count: number;
}

export interface CriteriaOverview {
  template: { key: string; name: string; description: string };
  review_threshold: number;
  go_threshold: number;
  criteria: Criterion[];
  rules: DecisionRule[];
  not_instrumented_rule: string;
  templates: CriteriaTemplate[];
  default_template_key: string;
}

export function getCriteria(): Promise<CriteriaOverview> {
  return apiRequest("/api/v1/criteria");
}
