/** Typed client for provider endpoints (M2). Sessions ride httpOnly cookies. */

import { apiRequest } from "./api";

export interface Provider {
  id: string;
  name: string;
  kind: string;
  model_name: string;
  base_url: string | null;
  is_active: boolean;
  timeout_seconds: number;
  max_retries: number;
  backoff_factor: number;
  rate_limit_per_minute: number;
  tokens_per_minute: number | null;
  is_premium: boolean;
  provider_config: Record<string, unknown> | null;
  connector: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProviderCreate {
  name: string;
  kind: string;
  model_name: string;
  base_url?: string | null;
  api_key?: string | null;
  timeout_seconds?: number;
  max_retries?: number;
  backoff_factor?: number;
  rate_limit_per_minute?: number;
  tokens_per_minute?: number | null;
  is_active?: boolean;
  metadata?: Record<string, unknown> | null;
  connector?: string | null;
}

export type ProviderUpdate = Partial<ProviderCreate>;

export const PRICE_IN_KEY = "price_per_1k_tokens_in";
export const PRICE_OUT_KEY = "price_per_1k_tokens_out";

/** What the user typed for one price: empty means "not set", never 0. */
export interface ParsedPrice {
  value: number | null;
  error: string | null;
}

export function parsePrice(raw: string): ParsedPrice {
  const text = raw.trim();
  if (text === "") {
    return { value: null, error: null };
  }
  const value = Number(text);
  if (!Number.isFinite(value)) {
    return { value: null, error: "Enter a number, or leave this empty." };
  }
  if (value < 0) {
    return { value: null, error: "A price cannot be negative." };
  }
  return { value, error: null };
}

/** The prices already stored on a provider, or nulls when it has none. */
export function storedPrices(config: Record<string, unknown> | null | undefined): {
  priceIn: number | null;
  priceOut: number | null;
} {
  const read = (key: string): number | null => {
    const raw = config?.[key];
    return typeof raw === "number" && Number.isFinite(raw) ? raw : null;
  };
  return { priceIn: read(PRICE_IN_KEY), priceOut: read(PRICE_OUT_KEY) };
}

export interface ProviderTestResult {
  success: boolean;
  message: string;
  latency_ms: number;
  model: string | null;
  is_free_tier: boolean | null;
  privacy_warning: string | null;
  connector: string;
  detected_answer?: string | null;
  detected_context?: unknown;
  fields?: Record<string, unknown>;
}

export function listProviders(): Promise<Provider[]> {
  return apiRequest("/api/v1/providers");
}

export function createProvider(body: ProviderCreate): Promise<Provider> {
  return apiRequest("/api/v1/providers", { method: "POST", body });
}

export function updateProvider(id: string, body: ProviderUpdate): Promise<Provider> {
  return apiRequest(`/api/v1/providers/${id}`, { method: "PATCH", body });
}

export function deleteProvider(id: string): Promise<void> {
  return apiRequest(`/api/v1/providers/${id}`, { method: "DELETE" });
}

export function testProvider(id: string): Promise<ProviderTestResult> {
  return apiRequest(`/api/v1/providers/${id}/test`, { method: "POST" });
}
