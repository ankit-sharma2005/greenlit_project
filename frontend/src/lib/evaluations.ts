/** Typed client for the metrics/decision preview endpoints (M5). */

import { apiRequest } from "./api";

export type Verdict = "GO" | "REVIEW" | "NO_GO";

export interface Criterion {
  metric: string;
  weight: number;
  threshold: number;
  hard_gate: boolean;
}

export interface CriteriaTemplate {
  key: string;
  name: string;
  description: string;
  review_threshold: number;
  go_threshold: number;
  criteria: Criterion[];
}

export interface TemplatesResponse {
  templates: CriteriaTemplate[];
  default: string;
}

export interface MetricRow {
  name: string;
  score: number;
  passed: boolean;
  explanation: string;
  instrumented: boolean;
  weight: number;
  threshold: number;
  hard_gate: boolean;
  details: Record<string, unknown>;
}

export interface FailedCase {
  input: string;
  expected: string;
  actual: string;
  reason: string;
}

export interface PreviewResponse {
  profile: string;
  profile_name: string;
  verdict: Verdict;
  score: number | null;
  rule: number;
  reason: string;
  review_threshold: number;
  go_threshold: number;
  suggested_fixes: string[];
  metrics: MetricRow[];
  failed_cases: FailedCase[];
  item_count: number;
  valid_items: number;
}

export interface PreviewRequest {
  profile: string;
  csv?: string;
  latency_limit_ms?: number;
}

export function listTemplates(): Promise<TemplatesResponse> {
  return apiRequest("/api/v1/evaluations/templates");
}

export function previewEvaluation(body: PreviewRequest): Promise<PreviewResponse> {
  return apiRequest("/api/v1/evaluations/preview", { method: "POST", body, timeoutMs: 60_000 });
}

/** Two ready-made helpdesk outputs so the page is usable without a file. */
export const SAMPLE_OUTPUTS: Record<"good" | "broken", string> = {
  good: [
    "input,expected_answer,output,reference_context,retrieved_context,latency_ms,tokens_in,tokens_out",
    [
      "What does the Merit Scholarship cover?",
      "The Merit Scholarship covers full tuition and fees for four years.",
      "The Merit Scholarship covers full tuition and fees for four years.",
      "The Merit Scholarship covers full tuition and fees for four years.",
      "Merit Scholarship: full tuition and fees, four years.",
      "420",
      "120",
      "60",
    ]
      .map(csvCell)
      .join(","),
    [
      "When is the library open?",
      "The library is open from 8 am to 10 pm on weekdays.",
      "The library is open from 8 am to 10 pm on weekdays.",
      "The library is open from 8 am to 10 pm on weekdays.",
      "Library hours: 8 am to 10 pm weekdays.",
      "380",
      "110",
      "45",
    ]
      .map(csvCell)
      .join(","),
    [
      "How do I appeal a grade?",
      "Submit a grade appeal form to the registrar within ten working days.",
      "Submit a grade appeal form to the registrar within ten working days.",
      "Submit a grade appeal form to the registrar within ten working days.",
      "Grade appeals: registrar, ten working days, form.",
      "510",
      "130",
      "70",
    ]
      .map(csvCell)
      .join(","),
  ].join("\n"),
  broken: [
    "input,expected_answer,output,reference_context,retrieved_context,latency_ms",
    [
      "What does the Merit Scholarship cover?",
      "The Merit Scholarship covers full tuition and fees for four years.",
      "I am not sure about that.",
      "The Merit Scholarship covers full tuition and fees for four years.",
      "Office hours are 9 to 5 in building C.",
      "9000",
    ]
      .map(csvCell)
      .join(","),
    [
      "When is the library open?",
      "The library is open from 8 am to 10 pm on weekdays.",
      "Please contact the department.",
      "The library is open from 8 am to 10 pm on weekdays.",
      "Office hours are 9 to 5 in building C.",
      "9400",
    ]
      .map(csvCell)
      .join(","),
    [
      "How do I appeal a grade?",
      "Submit a grade appeal form to the registrar within ten working days.",
      "No information available right now.",
      "Submit a grade appeal form to the registrar within ten working days.",
      "Office hours are 9 to 5 in building C.",
      "8700",
    ]
      .map(csvCell)
      .join(","),
  ].join("\n"),
};

function csvCell(value: string): string {
  return `"${value.replaceAll('"', '""')}"`;
}
