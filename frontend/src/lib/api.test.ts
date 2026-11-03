import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { API_BASE_URL, ApiError, apiRequest, apiUpload } from "./api";
import { isSessionExpired, onSessionExpired, resetRefreshState } from "./session";

function mockFetch(response: Partial<Response> & { json?: () => Promise<unknown> }) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({}),
    ...response,
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("apiRequest", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("defaults to the API on host port 8003 and sends cookies", async () => {
    const fetchMock = mockFetch({ json: async () => ({ ok: true }) });

    await apiRequest("/api/v1/auth/me");

    expect(API_BASE_URL).toBe("http://localhost:8003");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8003/api/v1/auth/me",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("parses the error envelope into an ApiError", async () => {
    mockFetch({
      ok: false,
      status: 401,
      json: async () => ({
        error: {
          code: "unauthorized",
          message: "Email or password is incorrect.",
          fields: [],
        },
      }),
    });

    await expect(apiRequest("/api/v1/auth/login", { method: "POST" })).rejects.toMatchObject({
      name: "ApiError",
      status: 401,
      code: "unauthorized",
      message: "Email or password is incorrect.",
    });
  });

  it("exposes validation fields", async () => {
    mockFetch({
      ok: false,
      status: 422,
      json: async () => ({
        error: {
          code: "validation_error",
          message: "Some fields are invalid.",
          fields: [{ field: "password", message: "String should have at least 10 characters" }],
        },
      }),
    });

    try {
      await apiRequest("/api/v1/auth/register", { method: "POST", body: {} });
      throw new Error("expected a rejection");
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      expect((error as ApiError).fields[0]?.field).toBe("password");
    }
  });

  it("reports the URL when the API is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await expect(apiRequest("/api/v1/auth/me")).rejects.toMatchObject({
      code: "network_error",
      message:
        "Cannot reach the GreenLit API at http://localhost:8003/api/v1/auth/me. Check that it is running, then try again.",
    });
  });

  it("reports the URL when an upload cannot reach the API", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await expect(apiUpload("/api/v1/datasets", new FormData())).rejects.toMatchObject({
      code: "network_error",
      message:
        "Cannot reach the GreenLit API at http://localhost:8003/api/v1/datasets. Check that it is running, then try again.",
    });
  });
});

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}

/** Counts calls per URL so a 401-then-200 endpoint can be written as a plain function. */
function callsTo(fetchMock: ReturnType<typeof vi.fn>, suffix: string): number {
  return fetchMock.mock.calls.filter(([url]) => String(url).endsWith(suffix)).length;
}

describe("apiRequest session refresh", () => {
  beforeEach(() => {
    resetRefreshState();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    resetRefreshState();
  });

  it("retries the request once after a successful refresh", async () => {
    const seen = new Map<string, number>();
    const fetchMock = vi.fn(async (url: string) => {
      if (String(url).endsWith("/auth/refresh")) return jsonResponse({ message: "ok" });
      const count = (seen.get(String(url)) ?? 0) + 1;
      seen.set(String(url), count);
      return count === 1
        ? jsonResponse({ error: { code: "unauthorized", message: "Token expired." } }, 401)
        : jsonResponse({ value: 42 });
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiRequest("/api/v1/datasets")).resolves.toEqual({ value: 42 });

    expect(seen.get(`${API_BASE_URL}/api/v1/datasets`)).toBe(2);
    expect(callsTo(fetchMock, "/auth/refresh")).toBe(1);
  });

  it("throws the original 401 and signals the session once when the refresh is refused", async () => {
    const fetchMock = vi.fn(async (url: string) =>
      String(url).endsWith("/auth/refresh")
        ? jsonResponse({ error: { code: "unauthorized", message: "No refresh cookie." } }, 401)
        : jsonResponse({ error: { code: "unauthorized", message: "Token expired." } }, 401),
    );
    vi.stubGlobal("fetch", fetchMock);
    const signal = vi.fn();
    const unsubscribe = onSessionExpired(signal);

    await expect(apiRequest("/api/v1/datasets")).rejects.toMatchObject({
      status: 401,
      message: "Token expired.",
    });

    expect(callsTo(fetchMock, "/auth/refresh")).toBe(1);
    expect(signal).toHaveBeenCalledTimes(1);
    expect(isSessionExpired()).toBe(true);
    unsubscribe();
  });

  it("treats a 403 refresh as expired as well", async () => {
    const fetchMock = vi.fn(async (url: string) =>
      String(url).endsWith("/auth/refresh")
        ? jsonResponse({ error: { code: "forbidden", message: "Revoked." } }, 403)
        : jsonResponse({ error: { code: "unauthorized", message: "Token expired." } }, 401),
    );
    vi.stubGlobal("fetch", fetchMock);
    const signal = vi.fn();
    const unsubscribe = onSessionExpired(signal);

    await expect(apiRequest("/api/v1/datasets")).rejects.toMatchObject({ status: 401 });

    expect(signal).toHaveBeenCalledTimes(1);
    unsubscribe();
  });

  it("shares one refresh between ten parallel 401s and retries all ten", async () => {
    const seen = new Map<string, number>();
    const fetchMock = vi.fn(async (url: string) => {
      if (String(url).endsWith("/auth/refresh")) {
        // A real refresh takes a round trip, so all ten callers arrive before it resolves.
        await new Promise((resolve) => setTimeout(resolve, 10));
        return jsonResponse({ message: "ok" });
      }
      const count = (seen.get(String(url)) ?? 0) + 1;
      seen.set(String(url), count);
      return count === 1
        ? jsonResponse({ error: { code: "unauthorized", message: "Token expired." } }, 401)
        : jsonResponse({ url });
    });
    vi.stubGlobal("fetch", fetchMock);

    const results = await Promise.all(
      Array.from({ length: 10 }, (_, index) => apiRequest<{ url: string }>(`/api/v1/datasets?i=${index}`)),
    );

    expect(results).toHaveLength(10);
    results.forEach((result, index) =>
      expect(result.url).toBe(`${API_BASE_URL}/api/v1/datasets?i=${index}`),
    );
    expect(callsTo(fetchMock, "/auth/refresh")).toBe(1);
  });

  it("does not loop when the request is still unauthorized after a good refresh", async () => {
    const fetchMock = vi.fn(async (url: string) =>
      String(url).endsWith("/auth/refresh")
        ? jsonResponse({ message: "ok" })
        : jsonResponse({ error: { code: "unauthorized", message: "Still not allowed." } }, 401),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiRequest("/api/v1/datasets")).rejects.toMatchObject({
      status: 401,
      message: "Still not allowed.",
    });

    expect(callsTo(fetchMock, "/api/v1/datasets")).toBe(2);
    expect(callsTo(fetchMock, "/auth/refresh")).toBe(1);
  });

  it.each(["/api/v1/auth/login", "/api/v1/auth/register", "/api/v1/auth/refresh", "/api/v1/auth/logout"])(
    "never refreshes on a 401 from %s",
    async (authPath) => {
      const called: string[] = [];
      const fetchMock = vi.fn(async (url: string) => {
        called.push(url);
        return jsonResponse(
          { error: { code: "unauthorized", message: "Wrong email or password." } },
          401,
        );
      });
      vi.stubGlobal("fetch", fetchMock);
      const signal = vi.fn();
      const unsubscribe = onSessionExpired(signal);

      await expect(apiRequest(authPath, { method: "POST" })).rejects.toMatchObject({ status: 401 });

      // Exactly one request, to the endpoint itself: no refresh was attempted.
      // (A call count on "/auth/refresh" cannot show that for the refresh path,
      // whose own request has the same URL.)
      expect(called).toEqual([`${API_BASE_URL}${authPath}`]);
      expect(signal).not.toHaveBeenCalled();
      unsubscribe();
    },
  );

  it("does not sign the user out when the refresh answers 500", async () => {
    const fetchMock = vi.fn(async (url: string) =>
      String(url).endsWith("/auth/refresh")
        ? jsonResponse({ error: { code: "server_error", message: "Boom." } }, 500)
        : jsonResponse({ error: { code: "unauthorized", message: "Token expired." } }, 401),
    );
    vi.stubGlobal("fetch", fetchMock);
    const signal = vi.fn();
    const unsubscribe = onSessionExpired(signal);

    await expect(apiRequest("/api/v1/datasets")).rejects.toMatchObject({
      status: 401,
      message: "Token expired.",
    });

    expect(signal).not.toHaveBeenCalled();
    expect(isSessionExpired()).toBe(false);
    unsubscribe();
  });

  it("does not sign the user out when the refresh cannot reach the API", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (String(url).endsWith("/auth/refresh")) throw new TypeError("Failed to fetch");
      return jsonResponse({ error: { code: "unauthorized", message: "Token expired." } }, 401);
    });
    vi.stubGlobal("fetch", fetchMock);
    const signal = vi.fn();
    const unsubscribe = onSessionExpired(signal);

    await expect(apiRequest("/api/v1/datasets")).rejects.toMatchObject({ status: 401 });

    expect(callsTo(fetchMock, "/auth/refresh")).toBe(1);
    expect(signal).not.toHaveBeenCalled();
    expect(isSessionExpired()).toBe(false);
    unsubscribe();
  });

  it("does not replay a body that cannot be read twice", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse({ error: { code: "unauthorized", message: "Token expired." } }, 401),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      apiRequest("/api/v1/runs", { method: "POST", body: new ReadableStream() }),
    ).rejects.toMatchObject({ status: 401 });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(callsTo(fetchMock, "/auth/refresh")).toBe(0);
  });
});
