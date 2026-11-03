import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  isSessionExpired,
  onSessionExpired,
  refreshSession,
  resetRefreshState,
} from "./session";

/** The refresh endpoint only needs `ok`/`status`; no test reads a body. */
function reply(status: number): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => ({}),
  } as Response;
}

function stubRefreshFetch(handler: () => Promise<Response> | Response) {
  const fetchMock = vi.fn(handler);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function installLocks(request: LockManager["request"]) {
  Object.defineProperty(navigator, "locks", { configurable: true, value: { request } });
}

describe("refreshSession", () => {
  beforeEach(() => {
    resetRefreshState();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    Reflect.deleteProperty(navigator, "locks");
    resetRefreshState();
  });

  it("posts to the refresh endpoint with cookies and reports ok", async () => {
    const fetchMock = stubRefreshFetch(() => reply(200));

    await expect(refreshSession()).resolves.toBe("ok");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8003/api/v1/auth/refresh",
      expect.objectContaining({ method: "POST", credentials: "include" }),
    );
    expect(isSessionExpired()).toBe(false);
  });

  it("shares one refresh between concurrent callers in the same tab", async () => {
    // A real refresh takes a round trip; the delay lets every caller arrive first.
    const fetchMock = stubRefreshFetch(
      () => new Promise<Response>((resolve) => setTimeout(() => resolve(reply(200)), 10)),
    );

    const outcomes = await Promise.all(Array.from({ length: 10 }, () => refreshSession()));

    expect(outcomes).toEqual(Array.from({ length: 10 }, () => "ok"));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("refreshes again on a later 401 once the first refresh has finished", async () => {
    const fetchMock = stubRefreshFetch(() => reply(200));

    await refreshSession();
    await refreshSession();

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("treats a 401 as an expired session and signals it once", async () => {
    stubRefreshFetch(() => reply(401));
    const signal = vi.fn();
    const unsubscribe = onSessionExpired(signal);

    await expect(refreshSession()).resolves.toBe("expired");

    expect(signal).toHaveBeenCalledTimes(1);
    expect(isSessionExpired()).toBe(true);
    unsubscribe();
  });

  it("treats a 403 as an expired session too", async () => {
    stubRefreshFetch(() => reply(403));
    const signal = vi.fn();
    const unsubscribe = onSessionExpired(signal);

    await expect(refreshSession()).resolves.toBe("expired");

    expect(signal).toHaveBeenCalledTimes(1);
    unsubscribe();
  });

  it("keeps the session on a server error", async () => {
    stubRefreshFetch(() => reply(500));
    const signal = vi.fn();
    const unsubscribe = onSessionExpired(signal);

    await expect(refreshSession()).resolves.toBe("error");

    expect(signal).not.toHaveBeenCalled();
    expect(isSessionExpired()).toBe(false);
    unsubscribe();
  });

  it("keeps the session when the refresh cannot reach the API", async () => {
    stubRefreshFetch(() => Promise.reject(new TypeError("Failed to fetch")));
    const signal = vi.fn();
    const unsubscribe = onSessionExpired(signal);

    await expect(refreshSession()).resolves.toBe("error");

    expect(signal).not.toHaveBeenCalled();
    expect(isSessionExpired()).toBe(false);
    unsubscribe();
  });

  it("runs the refresh inside navigator.locks.request('greenlit-refresh')", async () => {
    const names: string[] = [];
    let insideLock = false;
    let refreshRanInsideLock = false;
    stubRefreshFetch(() => {
      refreshRanInsideLock = insideLock;
      return reply(200);
    });
    const request = vi.fn(async (name: string, task: () => Promise<unknown>) => {
      names.push(name);
      insideLock = true;
      try {
        return await task();
      } finally {
        insideLock = false;
      }
    });
    installLocks(request as unknown as LockManager["request"]);

    await expect(refreshSession()).resolves.toBe("ok");

    expect(names).toEqual(["greenlit-refresh"]);
    expect(refreshRanInsideLock).toBe(true);
  });

  it("refreshes without Web Locks when the browser has none", async () => {
    expect((navigator as Navigator & { locks?: unknown }).locks).toBeUndefined();
    const fetchMock = stubRefreshFetch(() => reply(200));

    await expect(refreshSession()).resolves.toBe("ok");

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("refreshes anyway when taking the lock throws", async () => {
    const fetchMock = stubRefreshFetch(() => reply(200));
    installLocks((() => {
      throw new Error("SecurityError: lock denied");
    }) as unknown as LockManager["request"]);

    await expect(refreshSession()).resolves.toBe("ok");

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
