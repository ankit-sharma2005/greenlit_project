import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuditPanel } from "./AuditPanel";
import { ApiError } from "../lib/api";
import type { AuditEvent } from "../lib/audit";

const { listAuditEventsMock } = vi.hoisted(() => ({ listAuditEventsMock: vi.fn() }));

vi.mock("../lib/audit", () => ({ listAuditEvents: listAuditEventsMock }));

function event(overrides: Partial<AuditEvent> = {}): AuditEvent {
  return {
    id: "event-1",
    actor_id: "user-1",
    action: "auth.sign_in",
    target_type: "user",
    target_id: "user-1",
    event_metadata: { email: "admin@example.com" },
    ip_address: "127.0.0.1",
    created_at: "2026-10-29T09:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("AuditPanel", () => {
  it("lists events with the actor and the range of the page", async () => {
    listAuditEventsMock.mockResolvedValue({
      items: [event(), event({ id: "event-2", action: "run.start" })],
      total: 42,
      limit: 20,
      offset: 0,
    });

    render(<AuditPanel />);

    expect(await screen.findByTestId("audit-table")).toHaveTextContent("auth.sign_in");
    expect(screen.getAllByTestId("audit-row")).toHaveLength(2);
    expect(screen.getByTestId("audit-range")).toHaveTextContent("1–20 of 42");
  });

  it("filters by action on the server and resets to the first page", async () => {
    listAuditEventsMock.mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 });

    render(<AuditPanel />);
    await screen.findByTestId("audit-empty");

    await userEvent.type(screen.getByTestId("audit-action-filter"), "auth");

    await waitFor(() =>
      expect(listAuditEventsMock).toHaveBeenLastCalledWith({
        limit: 20,
        offset: 0,
        action: "auth",
        targetType: "",
      }),
    );
  });

  it("pages forward and back", async () => {
    listAuditEventsMock.mockResolvedValue({ items: [event()], total: 42, limit: 20, offset: 0 });

    render(<AuditPanel />);
    await screen.findByTestId("audit-table");
    expect(screen.getByTestId("audit-prev")).toBeDisabled();

    await userEvent.click(screen.getByTestId("audit-next"));

    await waitFor(() =>
      expect(listAuditEventsMock).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 20 })),
    );
  });

  it("shows the API's message when the log is admin-only and the user is not", async () => {
    listAuditEventsMock.mockRejectedValue(
      new ApiError("Your role does not allow this action.", 403, "forbidden"),
    );

    render(<AuditPanel />);

    expect(await screen.findByTestId("audit-error")).toHaveTextContent(
      "Your role does not allow this action.",
    );
  });
});
