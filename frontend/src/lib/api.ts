/** Browser API client. Sessions live in httpOnly cookies, so every request sends credentials. */

import { refreshSession } from "./session";

export const API_BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8003";

const REQUEST_TIMEOUT_MS = 20_000;

export interface ErrorField {
  field: string;
  message: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly fields: ErrorField[];

  constructor(message: string, status: number, code = "error", fields: ErrorField[] = []) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.fields = fields;
  }
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  timeoutMs?: number;
}

// Signing in, refreshing and signing out answer 401 for their own reasons; a
// refresh there would either recurse or hide the message the form shows.
const AUTH_PATHS = ["/api/v1/auth/login", "/api/v1/auth/register", "/api/v1/auth/refresh", "/api/v1/auth/logout"];

interface PreparedBody {
  init: BodyInit | undefined;
  json: boolean;
  /** False for a stream, which cannot be read twice. */
  replayable: boolean;
}

function prepareBody(body: unknown): PreparedBody {
  if (body === undefined) return { init: undefined, json: false, replayable: true };
  if (
    typeof body === "string" ||
    body instanceof URLSearchParams ||
    body instanceof FormData ||
    body instanceof Blob
  ) {
    return { init: body, json: false, replayable: true };
  }
  if (typeof ReadableStream !== "undefined" && body instanceof ReadableStream) {
    return { init: body, json: false, replayable: false };
  }
  return { init: JSON.stringify(body), json: true, replayable: true };
}

function fetchOnce(url: string, init: RequestInit, timeoutMs: number): Promise<Response> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  return fetch(url, { ...init, signal: controller.signal }).finally(() =>
    window.clearTimeout(timeout),
  );
}

/** Multipart upload (files travel as FormData; the browser sets the boundary). */
export async function apiUpload<T>(
  path: string,
  formData: FormData,
  timeoutMs = 120_000,
): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      credentials: "include",
      body: formData,
      signal: controller.signal,
    });

    const data: unknown = await response.json().catch(() => null);

    if (!response.ok) {
      const envelope = (data ?? {}) as ErrorEnvelope;
      throw new ApiError(
        envelope.error?.message ?? `Upload failed (HTTP ${response.status}).`,
        response.status,
        envelope.error?.code ?? "error",
        envelope.error?.fields ?? [],
      );
    }

    return data as T;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError(
        "The upload took too long. Try a smaller file, then try again.",
        0,
        "timeout",
      );
    }
    throw new ApiError(
      `Cannot reach the GreenLit API at ${API_BASE_URL}${path}. Check that it is running, then try again.`,
      0,
      "network_error",
    );
  } finally {
    window.clearTimeout(timeout);
  }
}

interface ErrorEnvelope {
  error?: {
    code?: string;
    message?: string;
    fields?: ErrorField[];
  };
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const prepared = prepareBody(options.body);
  const timeoutMs = options.timeoutMs ?? REQUEST_TIMEOUT_MS;
  const init: RequestInit = {
    method: options.method ?? "GET",
    credentials: "include",
    headers: prepared.json ? { "Content-Type": "application/json" } : undefined,
    body: prepared.init,
  };
  const url = `${API_BASE_URL}${path}`;

  try {
    let response = await fetchOnce(url, init, timeoutMs);
    // An expired access cookie looks like a 401 on any endpoint. Refresh once
    // (shared across concurrent 401s) and replay the request exactly once; a
    // second 401 after a good refresh falls through and throws below.
    const mayRefresh = !AUTH_PATHS.some((authPath) => path.startsWith(authPath));
    if (response.status === 401 && mayRefresh && prepared.replayable) {
      if ((await refreshSession()) === "ok") {
        response = await fetchOnce(url, init, timeoutMs);
      }
    }

    const data: unknown = await response.json().catch(() => null);

    if (!response.ok) {
      const envelope = (data ?? {}) as ErrorEnvelope;
      throw new ApiError(
        envelope.error?.message ?? `Request failed (HTTP ${response.status}).`,
        response.status,
        envelope.error?.code ?? "error",
        envelope.error?.fields ?? [],
      );
    }

    return data as T;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError(
        "The server took too long to answer. Check that your app and the API are running, then try again.",
        0,
        "timeout",
      );
    }
    throw new ApiError(
      `Cannot reach the GreenLit API at ${API_BASE_URL}${path}. Check that it is running, then try again.`,
      0,
      "network_error",
    );
  }
}
