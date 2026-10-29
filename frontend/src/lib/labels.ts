/** Typed client for the review queue, human labels and calibration (M7). */

import { apiRequest } from "./api";

export type HumanLabel = "pass" | "fail";

export interface ReviewCase {
  run_item_id: string;
  run_id: string;
  run_name: string;
  row_index: number;
  input_text: string;
  output: string | null;
  judge_score: number | null;
  judge_bucket: string | null;
  judge_confidence: number | null;
  judge_reason: string | null;
  reasons: string[];
  label: string | null;
  note: string | null;
}

export interface ReviewQueue {
  items: ReviewCase[];
  total: number;
}

export interface SavedLabel {
  id: string;
  run_id: string;
  run_item_id: string;
  reviewer_id: string;
  label: string;
  note: string | null;
  created_at: string;
  updated_at: string;
}

export interface CalibrationSummary {
  labelled: number;
  agreed: number;
  raw_agreement: number | null;
  kappa: number | null;
  reading: string;
}

export function listReviewQueue(): Promise<ReviewQueue> {
  return apiRequest("/api/v1/review/queue");
}

export function saveLabel(
  runItemId: string,
  label: HumanLabel,
  note?: string | null,
): Promise<SavedLabel> {
  return apiRequest(`/api/v1/review/items/${runItemId}/label`, {
    method: "POST",
    body: { label, note: note ?? null },
  });
}

export function getCalibration(): Promise<CalibrationSummary> {
  return apiRequest("/api/v1/review/calibration");
}
