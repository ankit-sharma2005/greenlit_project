import { apiRequest } from "./api";

export interface ConnectTestRequest {
  connector_type: "http_endpoint" | "prompt_app" | "upload_outputs";
  url?: string;
  method?: string;
  body_template?: string;
  headers?: Record<string, string>;
  /** cURL-imported headers and cookies, encrypted by the server. */
  headers_secret?: string;
  timeout_seconds?: number;
  allow_private_targets?: boolean;
  max_concurrency?: number;
  min_delay_ms?: number;
  max_retries?: number;
  response_format?: "json" | "sse" | "ndjson" | "text";
  stream_content_path?: string;
  answer_path?: string;
  context_path?: string;
  auto_detect?: boolean;
}

export interface ConnectTestResponse {
  success: boolean;
  message: string;
  trace?: Record<string, unknown> | null;
  detected_answer_path?: string | null;
  detected_context_path?: string | null;
  detected_request_shape?: string | null;
}

export function testConnection(body: ConnectTestRequest): Promise<ConnectTestResponse> {
  return apiRequest("/api/v1/connectors/test", { method: "POST", body });
}

export interface ParsedCurlResponse {
  method: string;
  url: string;
  /** Header names only: values never come back from the server. */
  header_names: string[];
  headers_secret: string | null;
  body_template: string | null;
  header_count: number;
}

export function parseCurl(curl: string): Promise<ParsedCurlResponse> {
  return apiRequest("/api/v1/connectors/curl/parse", { method: "POST", body: { curl } });
}
