import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { API_BASE_URL } from "../lib/api";
import { resetRefreshState } from "../lib/session";
import { AuthProvider } from "./AuthProvider";
import { useAuth } from "./authContext";

const USER = {
  id: "9f7f2c1a-0000-4000-8000-000000000000",
  email: "ada@example.com",
  name: "Ada",
  role: "admin" as const,
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
};

/** Shows the state the rest of the app would branch on. */
function Probe() {
  const { status, user } = useAuth();
  return <p data-testid="probe">{`${status}:${user?.email ?? "-"}`}</p>;
}

function reply(status: number, body: unknown = {}): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}

function renderProvider() {
  return render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  );
}

describe("AuthProvider session check", () => {
  beforeEach(() => {
    resetRefreshState();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    resetRefreshState();
  });

  it("refreshes after a 401 on mount and then signs the user in", async () => {
    let meCalls = 0;
    const fetchMock = vi.fn(async (url: string) => {
      if (String(url) === `${API_BASE_URL}/api/v1/auth/refresh`) return reply(200);
      meCalls += 1;
      return meCalls === 1
        ? reply(401, { error: { code: "unauthorized", message: "Token expired." } })
        : reply(200, USER);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderProvider();

    expect(await screen.findByText(`authenticated:${USER.email}`)).toBeInTheDocument();
    expect(meCalls).toBe(2);
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/auth/refresh"))).toHaveLength(
      1,
    );
  });

  it("stays anonymous on mount when the refresh is refused", async () => {
    const fetchMock = vi.fn(async (url: string) =>
      String(url) === `${API_BASE_URL}/api/v1/auth/refresh`
        ? reply(401, { error: { code: "unauthorized", message: "No refresh cookie." } })
        : reply(401, { error: { code: "unauthorized", message: "Token expired." } }),
    );
    vi.stubGlobal("fetch", fetchMock);

    renderProvider();

    expect(await screen.findByText("anonymous:-")).toBeInTheDocument();
    expect(screen.queryByText(`authenticated:${USER.email}`)).not.toBeInTheDocument();
  });

  it("signs in without a refresh when the cookie is still valid", async () => {
    const called: string[] = [];
    const fetchMock = vi.fn(async (url: string) => {
      called.push(url);
      return reply(200, USER);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderProvider();

    expect(await screen.findByText(`authenticated:${USER.email}`)).toBeInTheDocument();
    expect(called.filter((url) => url.endsWith("/auth/refresh"))).toEqual([]);
  });
});
