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
  checkTarget: vi.fn(),
  acceptTargetCheck: vi.fn(),
}));

vi.mock("../lib/targets", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/targets")>();
  return {
    ...actual,
    checkTarget: mocks.checkTarget,
    acceptTargetCheck: mocks.acceptTargetCheck,
  };
});

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

describe("NewTestPage run limits", () => {
  beforeEach(() => {
    mocks.testConnection.mockReset().mockResolvedValue(DETECTED);
    mocks.startRun.mockReset();
    mocks.quickTest.mockReset().mockResolvedValue({
      run: {
        id: "run-1",
        name: "Run",
        state: "queued",
        verdict: null,
        score: null,
        verdict_reason: null,
        is_partial: false,
        criteria_profile: "plain_chatbot",
        test_types: ["quality"],
        dataset_id: null,
        dataset_version_id: null,
        created_at: "2026-11-02T10:00:00Z",
        started_at: null,
        completed_at: null,
        progress: {
          items_done: 0,
          items_total: 0,
          items_failed: 0,
          items_cancelled: 0,
          stage: "queued",
          started_at: null,
          updated_at: null,
          elapsed_seconds: null,
        },
        metrics: [],
        failed_cases: [],
        judge: null,
        judge_skipped_reason: null,
        limits: null,
      },
      dataset_id: "dataset-1",
      dataset_version_id: "version-1",
      generated: true,
    });
    mocks.listDatasets.mockReset().mockResolvedValue({ items: [] });
    mocks.listProviders.mockReset().mockResolvedValue([]);
    mocks.loadDemo.mockReset();
  });

  async function detectLocalTarget() {
    await userEvent.click(screen.getByLabelText("This app runs on my computer"));
    await userEvent.type(screen.getByTestId("target-url"), "http://localhost:8000/chat");
    await userEvent.click(screen.getByTestId("start-test"));
    await screen.findByTestId("detect-result");
  }

  it("sends the caps the user typed with the run", async () => {
    renderPage();
    await detectLocalTarget();

    const cases = screen.getByTestId("max-cases");
    const duration = screen.getByTestId("max-duration");
    const tokens = screen.getByTestId("max-tokens");
    expect((duration as HTMLInputElement).value).toBe("1800");

    await userEvent.type(cases, "3");
    await userEvent.clear(duration);
    await userEvent.type(duration, "60");
    await userEvent.type(tokens, "5000");
    await userEvent.click(screen.getByTestId("run-full"));

    await waitFor(() => expect(mocks.quickTest).toHaveBeenCalledTimes(1));
    const [body] = mocks.quickTest.mock.calls[0] as [
      { max_cases?: number; max_duration_seconds?: number; max_total_tokens?: number },
    ];
    expect(body.max_cases).toBe(3);
    expect(body.max_duration_seconds).toBe(60);
    expect(body.max_total_tokens).toBe(5000);
  });

  it("sends no case or token cap when the boxes are empty", async () => {
    renderPage();
    await detectLocalTarget();

    expect((screen.getByTestId("max-cases") as HTMLInputElement).value).toBe("");
    await userEvent.click(screen.getByTestId("run-full"));

    await waitFor(() => expect(mocks.quickTest).toHaveBeenCalledTimes(1));
    const [body] = mocks.quickTest.mock.calls[0] as [
      { max_cases?: number; max_duration_seconds?: number; max_total_tokens?: number },
    ];
    // An empty box is "no cap", never a cap of zero (which would send nothing).
    expect(body.max_cases).toBeUndefined();
    expect(body.max_total_tokens).toBeUndefined();
    expect(body.max_duration_seconds).toBe(1800);
  });
});

function queuedRun() {
  return {
    id: "run-1",
    name: "Run",
    state: "queued",
    verdict: null,
    score: null,
    verdict_reason: null,
    is_partial: false,
    criteria_profile: "plain_chatbot",
    test_types: ["quality"],
    dataset_id: null,
    dataset_version_id: null,
    created_at: "2026-11-02T10:00:00Z",
    started_at: null,
    completed_at: null,
    progress: {
      items_done: 0,
      items_total: 0,
      items_failed: 0,
      items_cancelled: 0,
      stage: "queued",
      started_at: null,
      updated_at: null,
      elapsed_seconds: null,
    },
    metrics: [],
    failed_cases: [],
    judge: null,
    judge_skipped_reason: null,
    limits: null,
  };
}

describe("NewTestPage target check", () => {
  const CHECK = {
    check_id: "check-1",
    expires_at: "2026-11-02T10:30:00Z",
    accepted: false,
    request: {
      method: "POST",
      url: "https://chat.example.com/ask",
      headers: { Authorization: "XXXX" },
      body: '{"question": "Hello"}',
      input: "Hello",
    },
    status: 200,
    latency_ms: 42,
    answer: "GreenLit answers questions.",
    answer_truncated: false,
    extraction_ok: true,
    mapping_path: "answer",
    hint: null,
    error: null,
  };

  beforeEach(() => {
    mocks.testConnection.mockReset().mockResolvedValue(DETECTED);
    mocks.startRun.mockReset();
    mocks.quickTest.mockReset().mockResolvedValue({
      run: queuedRun(),
      dataset_id: "dataset-1",
      dataset_version_id: "version-1",
      generated: true,
    });
    mocks.listDatasets.mockReset().mockResolvedValue({ items: [] });
    mocks.listProviders.mockReset().mockResolvedValue([]);
    mocks.loadDemo.mockReset();
    mocks.checkTarget.mockReset().mockResolvedValue(CHECK);
    mocks.acceptTargetCheck.mockReset().mockResolvedValue({ ...CHECK, accepted: true });
  });

  async function detectRemoteTarget() {
    await userEvent.type(screen.getByTestId("target-url"), "https://chat.example.com/ask");
    await userEvent.click(screen.getByTestId("permission-confirmed"));
    await userEvent.click(screen.getByTestId("start-test"));
    await screen.findByTestId("detect-result");
  }

  async function acceptCheck() {
    await userEvent.click(screen.getByTestId("target-check-button"));
    await screen.findByTestId("target-check-result");
    await userEvent.click(screen.getByTestId("target-check-accept"));
    await waitFor(() => expect(mocks.acceptTargetCheck).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByTestId("run-full")).toBeEnabled());
  }

  it("keeps a remote run disabled until the extraction is accepted", async () => {
    renderPage();
    await detectRemoteTarget();

    expect(screen.getByTestId("target-check-panel")).toBeInTheDocument();
    expect(screen.getByTestId("run-full")).toBeDisabled();
    expect(screen.getByTestId("run-smoke")).toBeDisabled();
    expect(screen.getByTestId("run-full-blocked")).toBeInTheDocument();

    await userEvent.click(screen.getByTestId("target-check-button"));
    expect(await screen.findByTestId("target-check-result")).toHaveTextContent("HTTP 200");
    expect(screen.getByTestId("target-check-result")).toHaveTextContent("42 ms");
    expect(screen.getByTestId("target-check-answer")).toHaveTextContent(
      "GreenLit answers questions.",
    );
    expect(screen.getByTestId("target-check-result")).toHaveTextContent("path answer");
    expect(mocks.checkTarget).toHaveBeenCalledTimes(1);
    // Reading it is not accepting it.
    expect(screen.getByTestId("run-full")).toBeDisabled();

    await userEvent.click(screen.getByTestId("target-check-accept"));
    await waitFor(() => expect(mocks.acceptTargetCheck).toHaveBeenCalledWith("check-1"));
    await waitFor(() => expect(screen.getByTestId("run-full")).toBeEnabled());
  });

  it("sends the accepted check with a full run", async () => {
    renderPage();
    await detectRemoteTarget();
    await acceptCheck();

    await userEvent.click(screen.getByTestId("run-full"));
    await waitFor(() => expect(mocks.quickTest).toHaveBeenCalledTimes(1));
    const [body] = mocks.quickTest.mock.calls[0] as [
      { target_check_id?: string; is_smoke?: boolean; max_cases?: number },
    ];
    expect(body.target_check_id).toBe("check-1");
    expect(body.is_smoke).toBe(false);
    expect(body.max_cases).toBeUndefined();
  });

  it("starts a five-case smoke run from the smoke button", async () => {
    renderPage();
    await detectRemoteTarget();
    await acceptCheck();

    await userEvent.click(screen.getByTestId("run-smoke"));
    await waitFor(() => expect(mocks.quickTest).toHaveBeenCalledTimes(1));
    const [body] = mocks.quickTest.mock.calls[0] as [
      { target_check_id?: string; is_smoke?: boolean; max_cases?: number },
    ];
    expect(body.is_smoke).toBe(true);
    expect(body.max_cases).toBe(5);
    expect(body.target_check_id).toBe("check-1");
  });

  it("shows the hint when the extraction looks like a web page", async () => {
    mocks.checkTarget.mockResolvedValue({
      ...CHECK,
      answer: "<html>Please sign in</html>",
      extraction_ok: false,
      hint: "The answer looks like an HTML page, not a reply.",
    });
    renderPage();
    await detectRemoteTarget();
    await userEvent.click(screen.getByTestId("target-check-button"));

    expect(await screen.findByTestId("target-check-hint")).toHaveTextContent(
      "looks like an HTML page",
    );
    expect(screen.queryByTestId("target-check-accept")).not.toBeInTheDocument();
    expect(screen.getByTestId("run-full")).toBeDisabled();
  });
});
