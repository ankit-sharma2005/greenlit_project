/**
 * Typed client for the MCP server entry point.
 *
 * GreenLit calls one tool of a Streamable-HTTP MCP server once per case. The
 * browser only ever sends a URL, the encrypted header blob and the tool choice:
 * there is no stdio option and no command to run.
 */

import { apiRequest } from "./api";
import type { RunCreateRequest } from "./runs";

export interface McpTool {
  name: string;
  /** One bounded line of plain text: a server's own wording, never markup. */
  description: string;
  required_arguments: string[];
  string_arguments: string[];
  argument_names: string[];
  suggested_question_arg: string | null;
}

export interface McpToolsResponse {
  server: string | null;
  tools: McpTool[];
  target: string;
}

export interface McpToolsRequest {
  target: string;
  headers_secret?: string;
  header_names?: string[];
  timeout_seconds?: number;
  allow_private_targets?: boolean;
  permission_confirmed?: boolean;
  permission_reference?: string;
  max_retries?: number;
}

export function listMcpTools(body: McpToolsRequest): Promise<McpToolsResponse> {
  return apiRequest("/api/v1/targets/mcp/tools", { method: "POST", body });
}

export interface EncryptedHeaders {
  headers_secret: string;
  header_names: string[];
}

/** Encrypt a header value through the same path a pasted cURL uses. */
export function encryptHeaders(headers: Record<string, string>): Promise<EncryptedHeaders> {
  return apiRequest("/api/v1/connectors/headers/encrypt", { method: "POST", body: { headers } });
}

export interface ExtraArgsResult {
  value?: Record<string, unknown>;
  error?: string;
}

/** The extra-arguments box: an empty box is fine, anything else must be an object. */
export function parseExtraArgs(text: string): ExtraArgsResult {
  const trimmed = text.trim();
  if (!trimmed) return { value: {} };
  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    return { error: "The extra arguments must be valid JSON." };
  }
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    return { error: 'The extra arguments must be a JSON object, like {"locale": "en"}.' };
  }
  return { value: parsed as Record<string, unknown> };
}

export interface McpConfig {
  url: string;
  tool: string;
  questionArg: string;
  extraArgs: string;
  /** The encrypted blob from the server; the typed value is never kept. */
  headersSecret: string | null;
  headerNames: string[];
}

export interface McpPayloadInput {
  config: McpConfig;
  allowPrivate: boolean;
  permissionConfirmed: boolean;
  permissionReference?: string;
  maxRetries?: number;
  timeoutSeconds?: number;
}

/**
 * The run request for an MCP target.
 *
 * A pure function on purpose: the payload is what a check and a run must agree
 * on, so it is built in one place instead of inside two long handlers.
 */
export function buildMcpRunPayload(input: McpPayloadInput): RunCreateRequest | null {
  const { value, error } = parseExtraArgs(input.config.extraArgs);
  if (error || !value) return null;
  const tool = input.config.tool.trim();
  const questionArg = input.config.questionArg.trim();
  if (!input.config.url.trim() || !tool || !questionArg) return null;
  return {
    entry_point: "mcp_server",
    target: input.config.url.trim(),
    method: "POST",
    mcp_tool: tool,
    mcp_question_arg: questionArg,
    mcp_extra_args: value,
    headers_secret: input.config.headersSecret ?? undefined,
    header_names: input.config.headerNames.length > 0 ? input.config.headerNames : undefined,
    timeout_seconds: input.timeoutSeconds ?? 60,
    allow_private_targets: input.allowPrivate,
    permission_confirmed: !input.allowPrivate && input.permissionConfirmed,
    permission_reference:
      !input.allowPrivate && input.permissionReference
        ? input.permissionReference.trim() || undefined
        : undefined,
    max_retries: input.maxRetries ?? 3,
  };
}
