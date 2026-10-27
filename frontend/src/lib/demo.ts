/** Typed client for the one-click demo endpoint (spec section 10). */

import { apiRequest } from "./api";

export interface DemoLoadResponse {
  name: string;
  dataset_id: string;
  dataset_version_id: string;
  good_url: string;
  broken_url: string;
}

/** Seed (or reuse) this account's demo dataset and report the demo targets. */
export function loadDemo(): Promise<DemoLoadResponse> {
  return apiRequest("/api/v1/demo/load", { method: "POST", timeoutMs: 60_000 });
}
