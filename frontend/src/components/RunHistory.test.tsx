import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RunHistory } from "./RunHistory";
import type { Run } from "../lib/runs";

const { listRunsMock, getRunMock } = vi.hoisted(() => ({
  listRunsMock: vi.fn(),
  getRunMock: vi.fn(),
}));

vi.mock("../lib/runs", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/runs")>();
  return {
    ...actual,
    listRuns: listRunsMock,
    getRun: getRunMock,
  };
});

function makeMetric(name: string, score: number, instrumented = true): Run["metrics"][number] {
  return {
    name,
    score,
    passed: score >= 0.6,
    explanation: `${name} measured`,
    instrumented,
    weight: 0.5,
    threshold: 0.6,
    hard_gate: false,
    details: {},
  };
}

function makeRun(overrides: Partial<Run> = {}): Run {
  return {
    id: "4f0c1a9e-0000-4000-8000-000000000001",
    name: "HTTP endpoint test",
    entry_point: "http_endpoint",
    state: "completed",
    verdict: "GO",
    score: 0.92,
    verdict_reason: "Weighted score 0.92 is above the GO threshold 0.80.",
    is_partial: false,
    criteria_profile: "rag_chatbot",
    test_types: ["quality", "operations"],
    dataset_id: null,
    dataset_version_id: null,
    created_at: "2026-10-26T09:00:00Z",
    started_at: "2026-10-26T09:00:00Z",
    completed_at: "2026-10-26T09:01:00Z",
    progress: {
      items_done: 2,
      items_total: 2,
      items_failed: 0,
      items_cancelled: 0,
      stage: "finished",
      started_at: "2026-10-26T09:00:00Z",
      updated_at: "2026-10-26T09:01:00Z",
      elapsed_seconds: 60,
    },
    metrics: [makeMetric("answer_match", 1)],
    failed_cases: [],
    ...overrides,
  };
}

const OLD_RUN = makeRun({
  id: "4f0c1a9e-0000-4000-8000-000000000002",
  name: "Baseline run",
  verdict: "REVIEW",
  score: 0.71,
  verdict_reason: "Weighted score 0.71 is below the GO threshold 0.80.",
  metrics: [makeMetric("answer_match", 0.5), makeMetric("tool_call_match", 0.4)],
});

const NEW_RUN = makeRun({
  id: "4f0c1a9e-0000-4000-8000-000000000003",
  name: "Current run",
  metrics: [
    makeMetric("answer_match", 1),
    makeMetric("tool_call_match", 0.4),
    makeMetric("retrieval_context_recall", 0, false),
  ],
});

describe("RunHistory", () => {
  beforeEach(() => {
    listRunsMock.mockReset();
    getRunMock.mockReset();
  });

  it("explains the empty state when there are no runs", async () => {
    listRunsMock.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
    render(<RunHistory />);

    expect(await screen.findByTestId("run-history-empty")).toBeInTheDocument();
    expect(screen.getByTestId("run-history-count")).toHaveTextContent("0");
    expect(screen.getByTestId("run-history-compare")).toBeDisabled();
  });

  it("lists runs and opens one run's verdict", async () => {
    listRunsMock.mockResolvedValue({
      items: [makeRun()],
      total: 1,
      limit: 50,
      offset: 0,
    });
    render(<RunHistory />);

    expect(await screen.findByTestId("run-history-table")).toBeInTheDocument();
    const rows = screen.getAllByTestId("run-history-row");
    expect(rows).toHaveLength(1);
    expect(screen.getByTestId("run-history-verdict")).toHaveTextContent("Go");
    expect(screen.getByTestId("run-history-score")).toHaveTextContent("0.92");

    getRunMock.mockResolvedValue(makeRun());
    await userEvent.click(screen.getByTestId("run-history-open"));

    expect(await screen.findByTestId("run-verdict")).toBeInTheDocument();
    expect(screen.getByTestId("run-verdict-word")).toHaveTextContent("Go");
    expect(screen.getByTestId("run-verdict-reason")).toHaveTextContent("GO threshold 0.80");
  });

  it("compares two runs metric by metric", async () => {
    listRunsMock.mockResolvedValue({
      items: [OLD_RUN, NEW_RUN],
      total: 2,
      limit: 50,
      offset: 0,
    });
    render(<RunHistory />);

    await screen.findByTestId("run-history-table");
    const selects = screen.getAllByTestId("run-history-select");
    expect(screen.getByTestId("run-history-compare")).toBeDisabled();

    await userEvent.click(selects[0] as HTMLElement);
    expect(screen.getByTestId("run-history-compare")).toBeDisabled();
    await userEvent.click(selects[1] as HTMLElement);
    expect(screen.getByTestId("run-history-compare")).toBeEnabled();

    getRunMock.mockImplementation(async (id: string) => (id === OLD_RUN.id ? OLD_RUN : NEW_RUN));
    await userEvent.click(screen.getByTestId("run-history-compare"));

    const compare = await screen.findByTestId("run-compare-table");
    expect(compare).toBeInTheDocument();
    expect(screen.getByTestId("compare-baseline-verdict")).toHaveTextContent("Review");
    expect(screen.getByTestId("compare-candidate-verdict")).toHaveTextContent("Go");
    expect(screen.getByTestId("compare-baseline-score")).toHaveTextContent("0.71");
    expect(screen.getByTestId("compare-candidate-score")).toHaveTextContent("0.92");
    await waitFor(() =>
      expect(screen.getByTestId("compare-score-delta")).toHaveTextContent("+0.21"),
    );

    const changes = screen.getAllByTestId("compare-change");
    // Rows are alphabetical: answer_match, retrieval_context_recall, tool_call_match.
    expect(changes[0]).toHaveTextContent("improved");
    expect(changes[1]).toHaveTextContent("not instrumented");
    expect(changes[2]).toHaveTextContent("unchanged");
  });

  it("keeps the compare selection to at most two runs", async () => {
    listRunsMock.mockResolvedValue({
      items: [OLD_RUN, NEW_RUN, makeRun({ id: "4f0c1a9e-0000-4000-8000-000000000004" })],
      total: 3,
      limit: 50,
      offset: 0,
    });
    render(<RunHistory />);

    await screen.findByTestId("run-history-table");
    const selects = screen.getAllByTestId("run-history-select");
    await userEvent.click(selects[0] as HTMLElement);
    await userEvent.click(selects[1] as HTMLElement);
    await userEvent.click(selects[2] as HTMLElement);

    // The oldest selection drops out so at most two runs are ever held.
    expect(screen.getAllByTestId("run-history-select")[0]).not.toBeChecked();
    expect(screen.getAllByTestId("run-history-select")[1]).toBeChecked();
    expect(screen.getAllByTestId("run-history-select")[2]).toBeChecked();
    expect(screen.getByTestId("run-history-compare")).toBeEnabled();
  });

  it("reports a failed list load instead of an empty history", async () => {
    listRunsMock.mockRejectedValue(new Error("boom"));
    render(<RunHistory />);

    expect(await screen.findByTestId("run-history-error")).toHaveTextContent(
      "Could not load your runs",
    );
  });
});
