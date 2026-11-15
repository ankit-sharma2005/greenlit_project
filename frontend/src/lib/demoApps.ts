/** Typed client for the demo-app catalog (Settings → Demo apps). */

import { apiRequest } from "./api";
import type { SavedTarget } from "./savedTargets";

export interface DemoAppMode {
  mode: string;
  shows: string;
}

/** What the app's own /health said: only up/down and four known strings. */
export interface DemoAppStatus {
  state: "up" | "down";
  app?: string;
  mode?: string;
  provider?: string;
  model?: string;
}

export interface DemoApp {
  id: string;
  name: string;
  description: string;
  entry_point: string;
  url: string;
  method: string;
  response_format: string;
  answer_path: string | null;
  context_path: string | null;
  body_template: string | null;
  timeout_seconds: number;
  mcp_tool: string | null;
  start_bash: string;
  start_windows: string;
  modes: DemoAppMode[];
  status: DemoAppStatus;
}

export interface DemoAppsResponse {
  items: DemoApp[];
  warning: string;
}

export interface DemoConnectResponse {
  target: SavedTarget;
  created: boolean;
  warning: string;
}

export function listDemoApps(): Promise<DemoAppsResponse> {
  return apiRequest("/api/v1/demo-apps", { timeoutMs: 30_000 });
}

export function connectDemoApp(appId: string): Promise<DemoConnectResponse> {
  return apiRequest(`/api/v1/demo-apps/${encodeURIComponent(appId)}/connect`, {
    method: "POST",
  });
}
