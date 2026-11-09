/** Typed client for draft datasets: generate, review each item, publish approved ones. */

import { apiRequest } from "./api";
import type { DatasetVersion } from "./datasets";

export type DraftKind = "document_fact" | "unanswerable" | "paraphrase" | "edge_case";
export type DraftItemStatus = "pending" | "approved" | "rejected";

export interface DraftItem {
  id: string;
  row_index: number;
  question: string;
  expected_answer: string;
  source_passage: string | null;
  kind: string;
  status: DraftItemStatus;
  edited: boolean;
  generated_by_model: string;
  generator_provider: string;
  prompt_version: string;
  reviewed_at: string | null;
}

export interface DatasetDraft {
  id: string;
  name: string;
  app_description: string;
  requested_count: number;
  kinds: string[];
  generator_provider_id: string | null;
  generator_provider_name: string;
  generated_by_model: string;
  prompt_version: string;
  /** True when the generator is the same provider and model as the judge. */
  same_as_judge: boolean;
  status: string;
  published_dataset_id: string | null;
  published_version_id: string | null;
  created_at: string;
  items: DraftItem[];
}

export interface DraftListResponse {
  items: DatasetDraft[];
  total: number;
}

export interface DraftCreateBody {
  name: string;
  app_description: string;
  count: number;
  kinds: DraftKind[];
  documents?: string;
  provider_id?: string;
  model?: string;
}

export function listDrafts(): Promise<DraftListResponse> {
  return apiRequest("/api/v1/dataset-drafts");
}

export function getDraft(id: string): Promise<DatasetDraft> {
  return apiRequest(`/api/v1/dataset-drafts/${id}`);
}

export function createDraft(body: DraftCreateBody): Promise<DatasetDraft> {
  return apiRequest("/api/v1/dataset-drafts", { method: "POST", body, timeoutMs: 120_000 });
}

export function reviewDraftItem(
  draftId: string,
  itemId: string,
  patch: {
    status?: DraftItemStatus;
    question?: string;
    expected_answer?: string;
    source_passage?: string;
  },
): Promise<DatasetDraft> {
  return apiRequest(`/api/v1/dataset-drafts/${draftId}/items/${itemId}`, {
    method: "PATCH",
    body: patch,
  });
}

export function approveAllDraftItems(draftId: string): Promise<DatasetDraft> {
  return apiRequest(`/api/v1/dataset-drafts/${draftId}/items/approve-all`, { method: "POST" });
}

export function publishDraft(draftId: string): Promise<DatasetVersion> {
  return apiRequest(`/api/v1/dataset-drafts/${draftId}/publish`, { method: "POST" });
}
