/** Browser API client. Sessions live in httpOnly cookies, so every request sends credentials. */

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
      "Cannot reach the GreenLit API. Check that it is running, then try again.",
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
  const controller = new AbortController();
  const timeout = window.setTimeout(
    () => controller.abort(),
    options.timeoutMs ?? REQUEST_TIMEOUT_MS,
  );

  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      method: options.method ?? "GET",
      credentials: "include",
      headers: options.body === undefined ? undefined : { "Content-Type": "application/json" },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: controller.signal,
    });

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
      "Cannot reach the GreenLit API. Check that it is running, then try again.",
      0,
      "network_error",
    );
  } finally {
    window.clearTimeout(timeout);
  }
}
