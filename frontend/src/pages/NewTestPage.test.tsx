import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NewTestPage } from "./NewTestPage";

const mocks = vi.hoisted(() => ({
  testConnection: vi.fn(),
  startRun: vi.fn(),
  quickTest: vi.fn(),
  getRun: vi.fn(),
  cancelRun: vi.fn(),
  listDatasets: vi.fn(),
  listProviders: vi.fn(),
  loadDemo: vi.fn(),
}));

vi.mock("../lib/connectors", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/connectors")>();
  return { ...actual, testConnection: mocks.testConnection, parseCurl: vi.fn() };
});

vi.mock("../lib/runs", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/runs")>();
  return {
    ...actual,
    startRun: mocks.startRun,
    quickTest: mocks.quickTest,
    getRun: mocks.getRun,
    cancelRun: mocks.cancelRun,
  };
});

vi.mock("../lib/datasets", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/datasets")>();
  return { ...actual, listDatasets: mocks.listDatasets };
});

vi.mock("../lib/providers", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/providers")>();
  return { ...actual, listProviders: mocks.listProviders };
});

vi.mock("../lib/demo", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/demo")>();
  return { ...actual, loadDemo: mocks.loadDemo };
});

const DETECTED = {
  success: true,
  message: "Connection test successful",
  detected_answer_path: "answer",
  detected_context_path: null,
  detected_request_shape: '{"question": {{input}}}',
};

function renderPage() {
  return render(
    <MemoryRouter>
      <NewTestPage />
    </MemoryRouter>,
  );
}

describe("NewTestPage permission record", () => {
  beforeEach(() => {
    mocks.testConnection.mockReset().mockResolvedValue(DETECTED);
    mocks.startRun.mockReset().mockResolvedValue({
      id: "run-1",
      name: "Run",
      state: "queued",
      progress: { items_done: 0, items_total: 0 },
    });
    mocks.quickTest.mockReset();
    mocks.getRun.mockReset();
    mocks.cancelRun.mockReset();
    mocks.listDatasets.mockReset().mockResolvedValue({ items: [] });
    mocks.listProviders.mockReset().mockResolvedValue([]);
    mocks.loadDemo.mockReset();
  });

  it("refuses to test a remote app until permission is confirmed", async () => {
    renderPage();

    await userEvent.type(screen.getByTestId("target-url"), "https://chat.example.com/ask");
    await userEvent.click(screen.getByTestId("start-test"));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Confirm that you own this application or have permission to test it",
    );
    expect(mocks.testConnection).not.toHaveBeenCalled();
  });

  it("sends the confirmation and the reference with the request", async () => {
    renderPage();

    await userEvent.type(screen.getByTestId("target-url"), "https://chat.example.com/ask");
    await userEvent.click(screen.getByTestId("permission-confirmed"));
    await userEvent.type(screen.getByTestId("permission-reference"), "Ops ticket 4711");
    await userEvent.click(screen.getByTestId("start-test"));

    await waitFor(() => expect(mocks.testConnection).toHaveBeenCalledTimes(1));
    const [body] = mocks.testConnection.mock.calls[0] as [
      {
        permission_confirmed?: boolean;
        permission_reference?: string;
        safety_attacks_confirmed?: boolean;
        allow_private_targets?: boolean;
      },
    ];
    expect(body.permission_confirmed).toBe(true);
    expect(body.permission_reference).toBe("Ops ticket 4711");
    // Attack probes are a second, separate yes and start off.
    expect(body.safety_attacks_confirmed).toBe(false);
    expect(body.allow_private_targets).toBe(false);
  });

  it("keeps attack probes off until the second box repeats the permission", async () => {
    renderPage();

    await userEvent.type(screen.getByTestId("target-url"), "https://chat.example.com/ask");
    const attacks = screen.getByTestId("safety-attacks-confirmed") as HTMLInputElement;
    expect(attacks.checked).toBe(false);
    expect(attacks.disabled).toBe(true);

    await userEvent.click(screen.getByTestId("permission-confirmed"));
    expect((screen.getByTestId("safety-attacks-confirmed") as HTMLInputElement).disabled).toBe(
      false,
    );
    await userEvent.click(screen.getByTestId("safety-attacks-confirmed"));
    await userEvent.click(screen.getByTestId("start-test"));

    await waitFor(() => expect(mocks.testConnection).toHaveBeenCalledTimes(1));
    const [body] = mocks.testConnection.mock.calls[0] as [{ safety_attacks_confirmed?: boolean }];
    expect(body.safety_attacks_confirmed).toBe(true);
  });

  it("does not ask for permission when the app runs on this computer", async () => {
    renderPage();

    await userEvent.click(screen.getByLabelText("This app runs on my computer"));
    expect(screen.queryByTestId("permission-block")).not.toBeInTheDocument();

    await userEvent.type(screen.getByTestId("target-url"), "http://localhost:8000/chat");
    await userEvent.click(screen.getByTestId("start-test"));

    await waitFor(() => expect(mocks.testConnection).toHaveBeenCalledTimes(1));
    const [body] = mocks.testConnection.mock.calls[0] as [
      { allow_private_targets?: boolean; permission_confirmed?: boolean },
    ];
    expect(body.allow_private_targets).toBe(true);
    expect(body.permission_confirmed).toBe(false);
  });
});
