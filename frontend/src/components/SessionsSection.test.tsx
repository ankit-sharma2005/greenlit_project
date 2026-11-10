import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SessionsSection } from "./SessionsSection";
import { AuthContext, type AuthContextValue } from "../auth/authContext";
import {
  fetchSessions,
  revokeOtherSessions,
  revokeSession,
  type SessionRow,
} from "../lib/sessions";

vi.mock("../lib/sessions", () => ({
  fetchSessions: vi.fn(),
  revokeSession: vi.fn(),
  revokeOtherSessions: vi.fn(),
}));

// The zone is not what this test is about; the fetch behind this hook is a network call.
vi.mock("../lib/useAccountPreferences", () => ({
  useAccountPreferences: () => ({ theme: "dark", time_zone: "UTC" }),
}));

const CURRENT: SessionRow = {
  id: "11111111-1111-4111-8111-111111111111",
  device: "Chrome on Windows",
  created_at: "2026-01-02T03:04:05Z",
  last_activity: "2026-01-02T04:05:06Z",
  current: true,
};

const OTHER: SessionRow = {
  id: "22222222-2222-4222-8222-222222222222",
  device: "Firefox on Linux",
  created_at: "2026-01-01T00:00:00Z",
  last_activity: "2026-01-01T00:10:00Z",
  current: false,
};

function renderSection() {
  const value: AuthContextValue = {
    user: null,
    status: "authenticated",
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn().mockResolvedValue(undefined),
    updateProfile: vi.fn(),
  };
  render(
    <MemoryRouter>
      <AuthContext.Provider value={value}>
        <SessionsSection />
      </AuthContext.Provider>
    </MemoryRouter>,
  );
  return value;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchSessions).mockResolvedValue([CURRENT, OTHER]);
});

describe("SessionsSection", () => {
  it("lists every device, marks this one and labels the time as last activity", async () => {
    renderSection();

    await waitFor(() => expect(screen.getAllByTestId("session-row")).toHaveLength(2));
    const rows = screen.getAllByTestId("session-row");
    expect(rows[0]).toHaveAttribute("data-current", "true");
    expect(screen.getByTestId("session-current")).toHaveTextContent("This device");
    expect(screen.getAllByText(/Last activity/)).toHaveLength(2);
    // Never "last seen": the product has no last-used field.
    expect(screen.queryByText(/last seen/i)).toBeNull();
  });

  it("shows the API's own label when a device's agent is unknown", async () => {
    vi.mocked(fetchSessions).mockResolvedValue([CURRENT, { ...OTHER, device: "unknown device" }]);
    renderSection();

    expect(await screen.findByText("unknown device")).toBeInTheDocument();
  });

  it("asks before signing out the other devices, and cancelling does nothing", async () => {
    const user = userEvent.setup();
    renderSection();

    await user.click(await screen.findByTestId("session-revoke-others"));

    expect(screen.getByTestId("session-confirm")).toHaveTextContent("This device stays signed in");
    await user.click(screen.getByTestId("session-revoke-others-cancel"));

    expect(screen.queryByTestId("session-confirm")).toBeNull();
    expect(revokeOtherSessions).not.toHaveBeenCalled();
  });

  it("signs the other devices out only after confirmation", async () => {
    vi.mocked(revokeOtherSessions).mockResolvedValue(1);
    const user = userEvent.setup();
    renderSection();

    await user.click(await screen.findByTestId("session-revoke-others"));
    await user.click(screen.getByTestId("session-revoke-others-confirm"));

    expect(revokeOtherSessions).toHaveBeenCalledTimes(1);
    expect(await screen.findByTestId("sessions-notice")).toHaveTextContent(
      "Signed out 1 other device.",
    );
  });

  it("signs one other device out and says so", async () => {
    vi.mocked(revokeSession).mockResolvedValue("That device has been signed out.");
    vi.mocked(fetchSessions)
      .mockResolvedValueOnce([CURRENT, OTHER])
      .mockResolvedValueOnce([CURRENT]);
    const user = userEvent.setup();
    renderSection();

    const rows = await screen.findAllByTestId("session-row");
    // Rows are ordered as the API sends them: current first, then the other device.
    const otherRow = rows.find((row) => row.dataset.current === "false");
    if (!otherRow) throw new Error("the other device's row is missing");
    await user.click(within(otherRow).getByTestId("session-revoke"));

    expect(revokeSession).toHaveBeenCalledWith(OTHER.id);
    expect(await screen.findByTestId("sessions-notice")).toHaveTextContent(
      "That device has been signed out.",
    );
    await waitFor(() => expect(screen.getAllByTestId("session-row")).toHaveLength(1));
  });

  it("signing out this device signs the account out", async () => {
    vi.mocked(revokeSession).mockResolvedValue("Signed out this device.");
    const user = userEvent.setup();
    const context = renderSection();

    const rows = await screen.findAllByTestId("session-row");
    const currentRow = rows.find((row) => row.dataset.current === "true");
    if (!currentRow) throw new Error("this device's row is missing");
    await user.click(within(currentRow).getByTestId("session-revoke"));

    await waitFor(() => expect(context.logout).toHaveBeenCalled());
  });

  it("reports a failure instead of pretending the device is gone", async () => {
    vi.mocked(revokeSession).mockRejectedValue(new Error("network down"));
    const user = userEvent.setup();
    renderSection();

    const rows = await screen.findAllByTestId("session-row");
    const otherRow = rows.find((row) => row.dataset.current === "false");
    if (!otherRow) throw new Error("the other device's row is missing");
    await user.click(within(otherRow).getByTestId("session-revoke"));

    expect(await screen.findByTestId("sessions-error")).toHaveTextContent(
      "Could not sign that device out",
    );
    expect(screen.getAllByTestId("session-row")).toHaveLength(2);
  });
});
