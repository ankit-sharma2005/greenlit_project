import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConnectorsPanel } from "./ConnectorsPanel";
import { ApiError } from "../lib/api";
import type { SavedTarget } from "../lib/savedTargets";

const api = vi.hoisted(() => ({
  listSavedTargets: vi.fn(),
  createSavedTarget: vi.fn(),
  updateSavedTarget: vi.fn(),
  deleteSavedTarget: vi.fn(),
}));

vi.mock("../lib/savedTargets", () => api);

const support: SavedTarget = {
  id: "11111111-1111-4111-8111-111111111111",
  name: "Support bot",
  connector_type: "http_endpoint",
  url: "https://support.example.com/ask",
  method: "POST",
  body_template: null,
  header_names: [],
  answer_path: "$.answer",
  context_path: null,
  stream_content_path: null,
  response_format: "json",
  timeout_seconds: 60,
  max_concurrency: 1,
  min_delay_ms: 500,
  max_retries: 3,
  allow_private_targets: false,
  created_at: "2026-11-06T09:00:00Z",
  updated_at: "2026-11-06T09:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
  api.listSavedTargets.mockResolvedValue({ items: [support], total: 1 });
  api.createSavedTarget.mockResolvedValue(support);
  api.updateSavedTarget.mockResolvedValue({ ...support, name: "Support bot v2" });
  api.deleteSavedTarget.mockResolvedValue(undefined);
});

describe("ConnectorsPanel", () => {
  it("lists a saved target with its format and answer path", async () => {
    render(<ConnectorsPanel />);

    const row = await screen.findByTestId("connector-row-Support bot");
    expect(row).toHaveTextContent("POST https://support.example.com/ask");
    expect(row).toHaveTextContent("One JSON body");
    expect(row).toHaveTextContent("$.answer");
  });

  it("says plainly when nothing is saved", async () => {
    api.listSavedTargets.mockResolvedValue({ items: [], total: 0 });

    render(<ConnectorsPanel />);

    expect(await screen.findByTestId("connectors-none")).toHaveTextContent("Nothing saved yet");
  });

  it("saves a target and trims the boxes", async () => {
    render(<ConnectorsPanel />);
    await screen.findByTestId("connectors-table");

    await userEvent.type(screen.getByTestId("connector-name"), "  Support bot  ");
    await userEvent.type(
      screen.getByTestId("connector-url"),
      "  https://support.example.com/ask  ",
    );
    await userEvent.type(screen.getByTestId("connector-answer-path"), "  $.answer  ");
    await userEvent.click(screen.getByTestId("connector-save"));

    await waitFor(() =>
      expect(api.createSavedTarget).toHaveBeenCalledWith({
        name: "Support bot",
        url: "https://support.example.com/ask",
        method: "POST",
        response_format: "json",
        answer_path: "$.answer",
        // An empty box is stored as "no such field", not as an empty string.
        context_path: null,
        body_template: null,
        timeout_seconds: 60,
      }),
    );
    expect(await screen.findByTestId("connectors-notice")).toHaveTextContent(
      "“Support bot” is saved.",
    );
  });

  it("shows the API's own message when the name is taken", async () => {
    api.createSavedTarget.mockRejectedValue(
      new ApiError("You already saved a target named “Support bot”. Pick another name.", 409),
    );

    render(<ConnectorsPanel />);
    await screen.findByTestId("connectors-table");

    await userEvent.type(screen.getByTestId("connector-name"), "Support bot");
    await userEvent.type(screen.getByTestId("connector-url"), "https://other.example.com");
    await userEvent.click(screen.getByTestId("connector-save"));

    expect(await screen.findByTestId("connectors-error")).toHaveTextContent(
      "already saved a target named",
    );
  });

  it("edits an existing target in place", async () => {
    render(<ConnectorsPanel />);
    await screen.findByTestId("connectors-table");

    await userEvent.click(screen.getByTestId("connector-edit-Support bot"));
    // The form is filled from the saved row, not from empty defaults.
    expect(screen.getByTestId("connector-name")).toHaveValue("Support bot");
    expect(screen.getByTestId("connector-url")).toHaveValue("https://support.example.com/ask");
    expect(screen.getByTestId("connector-save")).toHaveTextContent("Save changes");

    await userEvent.clear(screen.getByTestId("connector-name"));
    await userEvent.type(screen.getByTestId("connector-name"), "Support bot v2");
    await userEvent.click(screen.getByTestId("connector-save"));

    await waitFor(() =>
      expect(api.updateSavedTarget).toHaveBeenCalledWith(
        support.id,
        expect.objectContaining({ name: "Support bot v2" }),
      ),
    );
    expect(await screen.findByTestId("connectors-notice")).toHaveTextContent(
      "“Support bot v2” was updated.",
    );
  });

  it("deletes a saved target and says so", async () => {
    render(<ConnectorsPanel />);
    await screen.findByTestId("connectors-table");

    await userEvent.click(screen.getByTestId("connector-delete-Support bot"));

    await waitFor(() => expect(api.deleteSavedTarget).toHaveBeenCalledWith(support.id));
    expect(await screen.findByTestId("connectors-notice")).toHaveTextContent(
      "“Support bot” was deleted.",
    );
  });

  it("reports a failure to load instead of showing an empty shelf", async () => {
    api.listSavedTargets.mockRejectedValue(
      new ApiError("Cannot reach the GreenLit API.", 0, "network_error"),
    );

    render(<ConnectorsPanel />);

    expect(await screen.findByTestId("connectors-error")).toHaveTextContent(
      "Cannot reach the GreenLit API.",
    );
  });
});
