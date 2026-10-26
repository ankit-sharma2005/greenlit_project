import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { RunProgressPanel } from "./RunProgressPanel";
import type { Run } from "../lib/runs";

function makeRun(overrides: Partial<Run> = {}): Run {
  return {
    id: "4f0c1a9e-0000-4000-8000-000000000001",
    name: "HTTP endpoint test",
    entry_point: "http_endpoint",
    state: "running",
    verdict: null,
    score: null,
    verdict_reason: null,
    is_partial: false,
    criteria_profile: "rag_chatbot",
    test_types: ["quality", "operations"],
    dataset_id: null,
    dataset_version_id: null,
    created_at: "2026-10-26T09:00:00Z",
    started_at: "2026-10-26T09:00:00Z",
    completed_at: null,
    progress: {
      items_done: 3,
      items_total: 10,
      items_failed: 1,
      items_cancelled: 0,
      stage: "running",
      started_at: "2026-10-26T09:00:00Z",
      updated_at: "2026-10-26T09:00:05Z",
      elapsed_seconds: 5,
    },
    metrics: [],
    failed_cases: [],
    ...overrides,
  };
}

describe("RunProgressPanel", () => {
  it("shows live counters, stage and a cancel button while running", async () => {
    const onCancel = vi.fn();
    render(<RunProgressPanel run={makeRun()} onCancel={onCancel} />);

    expect(screen.getByTestId("run-state")).toHaveTextContent("Running");
    expect(screen.getByTestId("run-counters")).toHaveTextContent("3 of 10 cases done");
    expect(screen.getByTestId("run-counters")).toHaveTextContent("1 failed");
    expect(screen.getByTestId("run-counters")).toHaveTextContent("5 s elapsed");
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "3");

    await userEvent.click(screen.getByTestId("cancel-run"));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("disables cancel while the run is already cancelling", () => {
    render(<RunProgressPanel run={makeRun({ state: "cancelling" })} onCancel={() => {}} />);

    expect(screen.getByTestId("run-state")).toHaveTextContent("Cancelling");
    expect(screen.getByTestId("cancel-run")).toBeDisabled();
  });

  it("shows the verdict with score, reason, metrics and failed cases", () => {
    render(
      <RunProgressPanel
        run={makeRun({
          state: "completed",
          verdict: "NO_GO",
          score: 0.51,
          verdict_reason:
            "Weighted score 0.51 is below the REVIEW threshold 0.60. " +
            "Weakest metrics: answer_match 0.00.",
          metrics: [
            {
              name: "answer_match",
              score: 0,
              passed: false,
              explanation: "no answer overlapped the expectation",
              instrumented: true,
              weight: 0.4,
              threshold: 0.6,
              hard_gate: false,
              details: {},
            },
            {
              name: "retrieval_context_recall",
              score: 0,
              passed: false,
              explanation: "retrieval was not instrumented",
              instrumented: false,
              weight: 0.25,
              threshold: 0.6,
              hard_gate: false,
              details: {},
            },
          ],
          failed_cases: [
            { input: "What is GreenLit?", expected: "", actual: "I am not sure.", reason: "wrong" },
          ],
        })}
        onCancel={() => {}}
      />,
    );

    expect(screen.queryByTestId("cancel-run")).not.toBeInTheDocument();
    expect(screen.getByTestId("run-verdict-word")).toHaveTextContent("No-Go");
    expect(screen.getByTestId("run-verdict-score")).toHaveTextContent("0.51");
    expect(screen.getByTestId("run-verdict-reason")).toHaveTextContent("REVIEW threshold 0.60");
    expect(screen.getByTestId("run-metrics")).toHaveTextContent("answer match");
    expect(screen.getByTestId("run-metrics")).toHaveTextContent("not instrumented");
    expect(screen.getByTestId("run-failed-cases")).toHaveTextContent("I am not sure.");
  });

  it("labels partial results after a cancel", () => {
    render(
      <RunProgressPanel
        run={makeRun({
          state: "cancelled",
          is_partial: true,
          verdict: "REVIEW",
          score: 0.7,
          verdict_reason: "This run was cancelled, so the results are partial.",
        })}
        onCancel={() => {}}
      />,
    );

    expect(screen.getByTestId("run-state")).toHaveTextContent("partial results");
    expect(screen.getByTestId("run-verdict-reason")).toHaveTextContent("partial");
  });
});
