import { afterEach, describe, expect, it, vi } from "vitest";

import { API_BASE_URL, ApiError, apiRequest } from "./api";

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

  it("reports an unreachable API in plain language", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await expect(apiRequest("/api/v1/auth/me")).rejects.toMatchObject({
      code: "network_error",
      message: "Cannot reach the GreenLit API. Check that it is running, then try again.",
    });
  });
});
