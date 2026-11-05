import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PreferencesPanel } from "./PreferencesPanel";
import { AuthContext, type AuthContextValue } from "../auth/authContext";
import { ApiError } from "../lib/api";
import { THEME_STORAGE_KEY } from "../lib/theme";
import { ThemeProvider } from "../theme/ThemeProvider";

const { fetchPreferencesMock, updatePreferencesMock } = vi.hoisted(() => ({
  fetchPreferencesMock: vi.fn(),
  updatePreferencesMock: vi.fn(),
}));

vi.mock("../lib/preferences", () => ({
  fetchPreferences: fetchPreferencesMock,
  updatePreferences: updatePreferencesMock,
}));

function renderPanel(): void {
  const value: AuthContextValue = {
    user: {
      id: "11111111-1111-4111-8111-111111111111",
      email: "ada@example.com",
      name: "Ada",
      role: "admin",
      is_active: true,
      created_at: "2026-01-02T03:04:05Z",
    },
    status: "authenticated",
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn().mockResolvedValue(undefined),
    updateProfile: vi.fn(),
  };

  render(
    <AuthContext.Provider value={value}>
      <ThemeProvider>
        <PreferencesPanel />
      </ThemeProvider>
    </AuthContext.Provider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  delete document.documentElement.dataset.theme;
  fetchPreferencesMock.mockResolvedValue({ theme: "dark" });
  updatePreferencesMock.mockResolvedValue({ theme: "dark" });
});

describe("PreferencesPanel", () => {
  it("applies a theme immediately and saves it to the account", async () => {
    renderPanel();
    expect(screen.getByTestId("theme-dark")).toBeChecked();

    await userEvent.click(screen.getByTestId("theme-light"));

    expect(document.documentElement.dataset.theme).toBe("light");
    expect(updatePreferencesMock).toHaveBeenCalledWith("light");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
    expect(await screen.findByTestId("preferences-notice")).toHaveTextContent("Appearance saved.");
  });

  it("restores the account's stored preference on load", async () => {
    fetchPreferencesMock.mockResolvedValue({ theme: "light" });

    renderPanel();

    await waitFor(() => expect(screen.getByTestId("theme-light")).toBeChecked());
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("resets to the default and says so", async () => {
    fetchPreferencesMock.mockResolvedValue({ theme: "light" });
    updatePreferencesMock.mockResolvedValue({ theme: "dark" });
    renderPanel();

    await waitFor(() => expect(screen.getByTestId("theme-light")).toBeChecked());
    await userEvent.click(screen.getByTestId("preferences-reset"));

    expect(updatePreferencesMock).toHaveBeenLastCalledWith("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(await screen.findByTestId("preferences-notice")).toHaveTextContent(
      "Preferences reset to the default theme.",
    );
  });

  it("keeps the choice when the save fails and offers a retry", async () => {
    updatePreferencesMock.mockRejectedValueOnce(
      new ApiError("Cannot reach the GreenLit API.", 0, "network_error"),
    );
    updatePreferencesMock.mockResolvedValueOnce({ theme: "light" });
    renderPanel();

    await userEvent.click(screen.getByTestId("theme-light"));

    expect(await screen.findByTestId("preferences-error")).toHaveTextContent(
      "Cannot reach the GreenLit API.",
    );
    // The theme still applies to this browser even though it was not stored.
    expect(document.documentElement.dataset.theme).toBe("light");

    await userEvent.click(screen.getByTestId("preferences-retry"));

    expect(updatePreferencesMock).toHaveBeenCalledTimes(2);
    expect(await screen.findByTestId("preferences-notice")).toHaveTextContent(
      "Preference saved to your account.",
    );
  });
});
