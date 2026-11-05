import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AccountPanel } from "./AccountPanel";
import { AuthContext, type AuthContextValue } from "../auth/authContext";
import { ApiError } from "../lib/api";
import type { CurrentUser } from "../lib/authApi";

const signedInUser: CurrentUser = {
  id: "11111111-1111-4111-8111-111111111111",
  email: "ada@example.com",
  name: "Ada",
  role: "admin",
  is_active: true,
  created_at: "2026-01-02T03:04:05Z",
};

function renderPanel(overrides: Partial<AuthContextValue> = {}): AuthContextValue {
  const value: AuthContextValue = {
    user: signedInUser,
    status: "authenticated",
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn().mockResolvedValue(undefined),
    updateProfile: vi.fn().mockResolvedValue(signedInUser),
    ...overrides,
  };

  render(
    <MemoryRouter>
      <AuthContext.Provider value={value}>
        <AccountPanel />
      </AuthContext.Provider>
    </MemoryRouter>,
  );
  return value;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("AccountPanel", () => {
  it("shows the signed-in user's real profile, including the creation date", () => {
    renderPanel();

    expect(screen.getByTestId("account-name-value")).toHaveTextContent("Ada");
    expect(screen.getByTestId("account-email")).toHaveTextContent("ada@example.com");
    expect(screen.getByTestId("account-role")).toHaveTextContent("admin");
    expect(screen.getByTestId("account-active")).toHaveTextContent("Active");
    expect(screen.getByTestId("account-created")).not.toHaveTextContent("Unknown");
    expect(screen.getByTestId("account-created")).toHaveTextContent("2026");
    expect(screen.getByTestId("account-id")).toHaveTextContent(signedInUser.id);
  });

  it("saves a trimmed display name and reports success", async () => {
    const context = renderPanel();
    const save = screen.getByTestId("account-save");
    expect(save).toBeDisabled();

    await userEvent.clear(screen.getByTestId("account-name"));
    await userEvent.type(screen.getByTestId("account-name"), "  Ada Lovelace  ");
    await userEvent.click(save);

    expect(context.updateProfile).toHaveBeenCalledWith({ name: "Ada Lovelace" });
    expect(await screen.findByTestId("account-notice")).toHaveTextContent("Display name saved.");
  });

  it("will not submit a blank display name", async () => {
    const context = renderPanel();

    await userEvent.clear(screen.getByTestId("account-name"));
    await userEvent.type(screen.getByTestId("account-name"), "   ");

    // Whitespace is not a name, so the save stays unavailable and nothing is sent.
    expect(screen.getByTestId("account-save")).toBeDisabled();
    expect(context.updateProfile).not.toHaveBeenCalled();
  });

  it("shows the API's own message when the save fails", async () => {
    renderPanel({
      updateProfile: vi
        .fn()
        .mockRejectedValue(new ApiError("Enter a display name.", 422, "validation_error")),
    });

    await userEvent.clear(screen.getByTestId("account-name"));
    await userEvent.type(screen.getByTestId("account-name"), "New Name");
    await userEvent.click(screen.getByTestId("account-save"));

    expect(await screen.findByTestId("account-error")).toHaveTextContent("Enter a display name.");
  });

  it("signs out through the existing session endpoint", async () => {
    const context = renderPanel();

    await userEvent.click(screen.getByTestId("account-sign-out"));

    expect(context.logout).toHaveBeenCalledTimes(1);
  });

  it("says the account is unavailable instead of inventing a profile", () => {
    renderPanel({ user: null, status: "anonymous" });

    expect(screen.getByTestId("account-unavailable")).toHaveTextContent(
      "Your account information is unavailable",
    );
    expect(screen.queryByTestId("account-email")).not.toBeInTheDocument();
  });
});
