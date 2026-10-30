import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DemoPanel } from "./DemoPanel";
import { ApiError } from "../lib/api";
import type { Run } from "../lib/runs";

const { loadDemoMock } = vi.hoisted(() => ({
  loadDemoMock: vi.fn(),
}));
vi.mock("../lib/demo", () => ({
  loadDemo: loadDemoMock,
}));

const { startRunMock } = vi.hoisted(() => ({
  startRunMock: vi.fn(),
}));
vi.mock("../lib/runs", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return {
    ...actual,
    startRun: startRunMock,
    isTerminal: (state: unknown) =>
      state === "succeeded" || state === "failed" || state === "completed",
  };
});

type DemoSetup = {
  dataset_version_id: string;
  good_url: string;
  broken_url: string;
};

function pendingRun(): Run {
  return {
    id: crypto.randomUUID(),
    name: "demo run",
    entry_point: "http_endpoint",
    state: "running",
    verdict: null,
    score: null,
    verdict_reason: null,
    is_partial: false,
    criteria_profile: "rag_chatbot",
    test_types: ["quality", "safety", "operations"],
    dataset_id: null,
    dataset_version_id: null,
    created_at: "2026-10-26T09:00:00Z",
    started_at: "2026-10-26T09:00:00Z",
    completed_at: null,
    progress: {
      items_done: 12,
      items_total: 12,
      items_failed: 0,
      items_cancelled: 0,
      stage: "running",
      started_at: "2026-10-26T09:00:00Z",
      updated_at: "2026-10-26T09:00:05Z",
      elapsed_seconds: 5,
    },
    metrics: [],
    failed_cases: [],
    judge: null,
    judge_skipped_reason: "This run had no judge profile.",
  } as unknown as Run;
}

function settledRun(verdict: string, score: number, reason: string): Run {
  return {
    id: crypto.randomUUID(),
    name: "demo run",
    entry_point: "http_endpoint",
    state: "succeeded",
    verdict,
    score,
    verdict_reason: reason,
    is_partial: false,
    criteria_profile: "rag_chatbot",
    test_types: ["quality", "safety", "operations"],
    dataset_id: null,
    dataset_version_id: null,
    created_at: "2026-10-26T09:00:00Z",
    started_at: "2026-10-26T09:00:00Z",
    completed_at: "2026-10-26T09:00:12Z",
    progress: {
      items_done: 12,
      items_total: 12,
      items_failed: 0,
      items_cancelled: 0,
      stage: "completed",
      started_at: "2026-10-26T09:00:00Z",
      updated_at: "2026-10-26T09:00:12Z",
      elapsed_seconds: 12,
    },
    metrics: [],
    failed_cases: [],
    judge: null,
    judge_skipped_reason: "This run had no judge profile.",
  } as unknown as Run;
}

function failedRun(reason: string): Run {
  const run = settledRun("NO_GO", 0.2, reason);
  return { ...run, state: "failed" } as Run;
}

const demoSetup: DemoSetup = {
  dataset_version_id: crypto.randomUUID(),
  good_url: "http://127.0.0.1:9991/ask",
  broken_url: "http://127.0.0.1:9992/ask",
};

beforeEach(() => {
  loadDemoMock.mockReset();
  startRunMock.mockReset();
  loadDemoMock.mockClear();
  startRunMock.mockClear();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("DemoPanel", () => {
  it("shows the demo hint until pressed", () => {
    const rendered = render(<DemoPanel />);
    expect(rendered.getByTestId("try-demo")).toHaveTextContent("Try the demo");
    expect(rendered.getByTestId("demo-hint")).toBeVisible();
  });

  it("shows both verdicts after Try the demo lands both runs", async () => {
    loadDemoMock.mockResolvedValue(demoSetup);
    startRunMock.mockResolvedValueOnce(settledRun("GO", 0.95, "Good"));
    startRunMock.mockResolvedValueOnce(settledRun("NO_GO", 0.42, "Low weighted score"));
    const user = userEvent.setup();
    const rendered = render(<DemoPanel />);

    await user.click(rendered.getByTestId("try-demo"));
    await waitFor(() => expect(rendered.getByTestId("demo-good-verdict")).toHaveTextContent("Go"), {
      timeout: 60_000,
    });
    expect(rendered.getByTestId("demo-good-score")).toHaveTextContent("0.95");
    expect(rendered.getByTestId("demo-broken-verdict")).toHaveTextContent("No-Go");
    expect(rendered.getByTestId("demo-broken-score")).toHaveTextContent("0.42");
    expect(rendered.getByTestId("demo-broken-reason")).toHaveTextContent("Low weighted score");
    expect(rendered.getByTestId("demo-results")).toHaveTextContent("Demo results");
    expect(rendered.getByTestId("demo-results-grid")).toContainElement(
      rendered.getByTestId("demo-good-result"),
    );
    expect(rendered.getByTestId("demo-results-grid")).toContainElement(
      rendered.getByTestId("demo-broken-result"),
    );
  });

  it("reports an error when the demo setup fails", async () => {
    loadDemoMock.mockRejectedValueOnce(new ApiError("demo app not reachable", 503));
    const user = userEvent.setup();
    const rendered = render(<DemoPanel />);

    await user.click(rendered.getByTestId("try-demo"));
    await waitFor(
      () => expect(rendered.getByTestId("demo-error")).toHaveTextContent("demo app not reachable"),
      { timeout: 60_000 },
    );
  });

  it("shows the unreachable banner when both runs fail", async () => {
    loadDemoMock.mockResolvedValue(demoSetup);
    startRunMock.mockResolvedValueOnce(failedRun("request failed"));
    startRunMock.mockResolvedValueOnce(failedRun("request failed"));
    const user = userEvent.setup();

    const rendered = render(<DemoPanel />);
    await user.click(rendered.getByTestId("try-demo"));
    await waitFor(() => expect(rendered.getByTestId("demo-unreachable")).toBeVisible(), {
      timeout: 60_000,
    });
  });

  it("keeps waiting when the first run is still in flight", async () => {
    loadDemoMock.mockResolvedValue(demoSetup);
    startRunMock.mockResolvedValueOnce(pendingRun());
    const user = userEvent.setup();
    const rendered = render(<DemoPanel />);

    await user.click(rendered.getByTestId("try-demo"));
    await waitFor(
      () => expect(rendered.getByTestId("try-demo")).toHaveTextContent("Running the demo"),
      { timeout: 120_000 },
    );
    expect(rendered.queryByTestId("demo-good-verdict")).toBeNull();
  });
});
