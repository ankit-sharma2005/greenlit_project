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
    judge: null,
    judge_skipped_reason: "This run had no judge profile.",
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

  it("names the judge model and rubric that scored the answers", () => {
    render(
      <RunProgressPanel
        run={makeRun({
          state: "completed",
          verdict: "REVIEW",
          score: 0.88,
          judge: {
            model: "gpt-4o-mini",
            provider_name: "OpenAI",
            profile_name: "The judge",
            rubric_version: "1.0",
            prompt_template_hash: "abc123",
            temperature: 0,
            max_tokens: 512,
            graded_items: 3,
            unavailable_items: 1,
            low_confidence_items: 0,
          },
          judge_skipped_reason: null,
        })}
        onCancel={() => {}}
      />,
    );

    expect(screen.getByTestId("run-verdict-judge")).toHaveTextContent("gpt-4o-mini");
    expect(screen.getByTestId("run-verdict-judge")).toHaveTextContent("rubric 1.0");
    expect(screen.getByTestId("run-verdict-judge-note")).toHaveTextContent(
      "could not score 1 answer",
    );
    expect(screen.queryByTestId("run-verdict-judge-skipped")).not.toBeInTheDocument();
  });

  it("says the judge was skipped when no judge was used", () => {
    render(
      <RunProgressPanel
        run={makeRun({
          state: "completed",
          verdict: "GO",
          score: 0.92,
          judge: null,
          judge_skipped_reason: "This run had no judge profile, so answer quality was not scored.",
        })}
        onCancel={() => {}}
      />,
    );

    expect(screen.getByTestId("run-verdict-judge")).toHaveTextContent("not used");
    expect(screen.getByTestId("run-verdict-judge-skipped")).toHaveTextContent("Judge skipped");
  });

  it("shows the safety section for a run that was probed", () => {
    render(
      <RunProgressPanel
        run={makeRun({
          state: "completed",
          verdict: "GO",
          score: 0.95,
          test_types: ["quality", "safety", "operations"],
          metrics: [
            {
              name: "attack_resisted",
              score: 1,
              passed: true,
              explanation: "the app resisted 44 of 44 attacks.",
              instrumented: true,
              weight: 0.2,
              threshold: 0.95,
              hard_gate: true,
              details: { attacks: 44, resisted: 44, critical_failures: [] },
            },
            {
              name: "over_refusal",
              score: 1,
              passed: true,
              explanation: "none of the 26 harmless requests were refused.",
              instrumented: true,
              weight: 0.05,
              threshold: 0.9,
              hard_gate: false,
              details: { prompts: 26, refused: 0, over_refusal_share: 0 },
            },
          ],
        })}
        onCancel={() => {}}
      />,
    );

    expect(screen.getByTestId("safety-section")).toBeInTheDocument();
    expect(screen.getByTestId("safety-resisted")).toHaveTextContent("44 of 44");
  });
});
