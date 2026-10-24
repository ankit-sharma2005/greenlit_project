/** Typed client for the dataset endpoints (M4). Sessions ride httpOnly cookies. */

import { apiRequest, apiUpload } from "./api";

export interface ColumnMapping {
  input_column: string;
  output_column: string;
  id_column: string | null;
  retrieved_context_column: string | null;
  latency_ms_column: string | null;
  tokens_in_column: string | null;
  tokens_out_column: string | null;
  detected: boolean;
}

export interface DatasetVersion {
  id: string;
  dataset_id: string;
  version_no: number;
  content_hash: string;
  row_count: number;
  columns_snapshot: Record<string, unknown> | null;
  generated: boolean;
  approved_by: string | null;
  approved_at: string | null;
  created_at: string;
}

export interface Dataset {
  id: string;
  owner_id: string;
  name: string;
  source_filename: string;
  file_format: string;
  content_hash: string;
  created_at: string;
  updated_at: string;
  columns: ColumnMapping | null;
  versions: DatasetVersion[];
}

export interface DatasetItem {
  id: string;
  dataset_version_id: string;
  row_index: number;
  data: Record<string, unknown>;
  created_at: string;
}

export interface DatasetListResponse {
  items: Dataset[];
  total: number;
  limit: number;
  offset: number;
}

export interface DatasetItemListResponse {
  items: DatasetItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface ProviderSummary {
  id: string;
  name: string;
  kind: string;
  model_name: string;
  is_active: boolean;
}

export function listDatasets(): Promise<DatasetListResponse> {
  return apiRequest("/api/v1/datasets");
}

export function uploadDataset(name: string, file: File): Promise<Dataset> {
  const form = new FormData();
  form.set("name", name);
  form.set("file", file);
  return apiUpload("/api/v1/datasets", form);
}

export function getDataset(id: string): Promise<Dataset> {
  return apiRequest(`/api/v1/datasets/${id}`);
}

export function listVersions(id: string): Promise<DatasetVersion[]> {
  return apiRequest(`/api/v1/datasets/${id}/versions`);
}

export function listItems(id: string, versionNo: number): Promise<DatasetItemListResponse> {
  return apiRequest(`/api/v1/datasets/${id}/versions/${versionNo}/items`);
}

export function approveVersion(id: string, versionNo: number): Promise<DatasetVersion> {
  return apiRequest(`/api/v1/datasets/${id}/versions/${versionNo}/approve`, { method: "POST" });
}

export interface GenerationRequest {
  provider_id: string;
  count: number;
  source_text?: string;
}

export function generateVersion(id: string, body: GenerationRequest): Promise<DatasetVersion> {
  return apiRequest(`/api/v1/datasets/${id}/generate`, { method: "POST", body });
}

export function deleteDataset(id: string): Promise<void> {
  return apiRequest(`/api/v1/datasets/${id}`, { method: "DELETE" });
}

export function listProviders(): Promise<ProviderSummary[]> {
  return apiRequest("/api/v1/providers");
}
