import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PreferencesPanel } from "./PreferencesPanel";
import { AuthContext, type AuthContextValue } from "../auth/authContext";
import { ThemeProvider } from "../theme/ThemeProvider";

const { fetchPreferencesMock, updatePreferencesMock } = vi.hoisted(() => ({
  fetchPreferencesMock: vi.fn(),
  updatePreferencesMock: vi.fn(),
}));

vi.mock("../lib/preferences", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/preferences")>();
  return {
    ...actual,
    fetchPreferences: fetchPreferencesMock,
    updatePreferences: updatePreferencesMock,
  };
});

const STORED = {
  theme: "dark" as const,
  entry_point: "prompt_app" as const,
  test_types: ["quality" as const],
  time_zone: "Europe/Berlin",
  show_full_answers: false,
};

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
  fetchPreferencesMock.mockResolvedValue(STORED);
  updatePreferencesMock.mockImplementation(
    (theme: string, _models: unknown, display: Record<string, unknown>) =>
      Promise.resolve({ ...STORED, ...display, theme }),
  );
});

describe("PreferencesPanel fields", () => {
  it("shows the stored entry point, test types, zone and answer length", async () => {
    renderPanel();

    await waitFor(() =>
      expect(screen.getByTestId("preferences-entry-point")).toHaveValue("prompt_app"),
    );
    expect(screen.getByTestId("preferences-test-type-quality")).toBeChecked();
    expect(screen.getByTestId("preferences-test-type-safety")).not.toBeChecked();
    expect(screen.getByTestId("preferences-time-zone")).toHaveValue("Europe/Berlin");
    expect(screen.getByTestId("preferences-full-answers")).not.toBeChecked();
  });

  it("saves a chosen entry point without disturbing the other keys", async () => {
    renderPanel();
    await waitFor(() => expect(screen.getByTestId("preferences-entry-point")).toHaveValue("prompt_app"));

    await userEvent.selectOptions(screen.getByTestId("preferences-entry-point"), "mcp_server");

    await waitFor(() => expect(updatePreferencesMock).toHaveBeenCalled());
    expect(updatePreferencesMock).toHaveBeenLastCalledWith(
      "dark",
      {},
      expect.objectContaining({
        entry_point: "mcp_server",
        test_types: ["quality"],
        time_zone: "Europe/Berlin",
        show_full_answers: false,
      }),
    );
    expect(await screen.findByTestId("preferences-notice")).toHaveTextContent(
      "Default entry point saved.",
    );
  });

  it("adds a test type to the stored set", async () => {
    renderPanel();
    await waitFor(() =>
      expect(screen.getByTestId("preferences-test-type-quality")).toBeChecked(),
    );

    await userEvent.click(screen.getByTestId("preferences-test-type-safety"));

    expect(updatePreferencesMock).toHaveBeenLastCalledWith(
      "dark",
      {},
      expect.objectContaining({ test_types: ["quality", "safety"] }),
    );
  });

  it("saves the answer-length toggle and the time zone", async () => {
    renderPanel();
    await waitFor(() => expect(screen.getByTestId("preferences-full-answers")).not.toBeChecked());

    await userEvent.click(screen.getByTestId("preferences-full-answers"));
    await userEvent.selectOptions(screen.getByTestId("preferences-time-zone"), "Asia/Tokyo");

    const calls = updatePreferencesMock.mock.calls.map((call) => call[2]);
    expect(calls).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ show_full_answers: true }),
        expect.objectContaining({ time_zone: "Asia/Tokyo" }),
      ]),
    );
  });

  it("reports a failed save instead of pretending it worked", async () => {
    updatePreferencesMock.mockRejectedValueOnce(new Error("offline"));
    renderPanel();
    await waitFor(() => expect(screen.getByTestId("preferences-full-answers")).not.toBeChecked());

    await userEvent.click(screen.getByTestId("preferences-full-answers"));

    expect(await screen.findByTestId("preferences-display-error")).toHaveTextContent(
      "could not be saved",
    );
  });
});
