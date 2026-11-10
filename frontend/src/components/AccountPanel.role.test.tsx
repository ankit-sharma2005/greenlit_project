import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AccountPanel } from "./AccountPanel";
import { AuthContext, type AuthContextValue } from "../auth/authContext";
import type { CurrentUser } from "../lib/authApi";
import { fetchSessions } from "../lib/sessions";

vi.mock("../lib/useAccountPreferences", () => ({
  useAccountPreferences: () => null,
}));

vi.mock("../lib/sessions", () => ({
  fetchSessions: vi.fn(),
  revokeSession: vi.fn(),
  revokeOtherSessions: vi.fn(),
}));

beforeEach(() => {
  // The project resets mock implementations between tests, so set it here.
  vi.mocked(fetchSessions).mockResolvedValue([]);
});

function renderWithRole(role: CurrentUser["role"]) {
  const user: CurrentUser = {
    id: "11111111-1111-4111-8111-111111111111",
    email: "ada@example.com",
    name: "Ada",
    role,
    is_active: true,
    created_at: "2026-01-02T03:04:05Z",
  };
  const value: AuthContextValue = {
    user,
    status: "authenticated",
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn().mockResolvedValue(undefined),
    updateProfile: vi.fn(),
  };
  render(
    <MemoryRouter>
      <AuthContext.Provider value={value}>
        <AccountPanel />
      </AuthContext.Provider>
    </MemoryRouter>,
  );
}

describe("AccountPanel role", () => {
  it("says in one sentence what a member may do", () => {
    renderWithRole("member");

    const note = screen.getByTestId("account-role-note");
    expect(note).toHaveTextContent("Member:");
    expect(note).toHaveTextContent("Providers and labels belong to admins and reviewers");
  });

  it("says what an admin may do", () => {
    renderWithRole("admin");

    expect(screen.getByTestId("account-role-note")).toHaveTextContent(
      "Admin: can run tests, manage providers",
    );
  });

  it("offers no control to promote or demote anybody", () => {
    renderWithRole("member");

    expect(screen.queryByRole("button", { name: /promote/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /demote/i })).toBeNull();
    expect(screen.queryByRole("combobox", { name: /role/i })).toBeNull();
    expect(screen.getByTestId("account-role")).toHaveTextContent("member");
  });
});
