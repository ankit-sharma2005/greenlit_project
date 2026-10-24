import { apiRequest } from "./api";

export interface ConnectTestRequest {
  connector_type: "http_endpoint" | "prompt_app" | "upload_outputs";
  url?: string;
  method?: string;
  body_template?: string;
  headers?: Record<string, string>;
  timeout_seconds?: number;
  allow_private_targets?: boolean;
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

export function parseCurl(curl: string) {
  return apiRequest("/api/v1/connectors/curl/parse", { method: "POST", body: { curl } });
}
