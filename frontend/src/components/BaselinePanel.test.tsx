import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BaselinePanel } from "./BaselinePanel";
import { ApiError } from "../lib/api";
import type { Baseline } from "../lib/baselines";
import type { Run } from "../lib/runs";

const { getBaselineMock, setBaselineMock, clearBaselineMock, getRunMock } = vi.hoisted(() => ({
  getBaselineMock: vi.fn(),
  setBaselineMock: vi.fn(),
  clearBaselineMock: vi.fn(),
  getRunMock: vi.fn(),
}));

vi.mock("../lib/baselines", () => ({
  getBaseline: getBaselineMock,
  setBaseline: setBaselineMock,
  clearBaseline: clearBaselineMock,
}));

vi.mock("../lib/runs", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/runs")>();
  return { ...actual, getRun: getRunMock };
});

const BASELINE: Baseline = {
  run_id: "baseline-run",
  run_name: "Release 1.2",
  dataset_id: "dataset-1",
  dataset_version_id: "version-1",
  metric_tolerance: 0.05,
  case_tolerance: 2,
  is_active: true,
  created_at: "2026-10-28T09:00:00Z",
  updated_at: "2026-10-28T09:00:00Z",
};

function makeRun(overrides: Partial<Run> = {}): Run {
  return {
    id: "run-1",
    name: "Nightly",
    entry_point: "http_endpoint",
    state: "completed",
    verdict: "NO_GO",
    score: 0.54,
    verdict_reason: "Weighted score 0.54 is below the REVIEW threshold 0.60.",
    is_partial: false,
    criteria_profile: "rag_chatbot",
    test_types: ["quality"],
    dataset_id: "dataset-1",
    dataset_version_id: "version-1",
    created_at: "2026-10-29T09:00:00Z",
    started_at: "2026-10-29T09:00:00Z",
    completed_at: "2026-10-29T09:01:00Z",
    progress: {
      items_done: 2,
      items_total: 2,
      items_failed: 0,
      items_cancelled: 0,
      stage: "completed",
      started_at: null,
      updated_at: null,
      elapsed_seconds: 60,
    },
    metrics: [],
    failed_cases: [],
    judge: null,
    judge_skipped_reason: "This run had no judge profile.",
    regression: null,
    is_baseline: false,
    ...overrides,
  };
}

const BLOCKED = {
  status: "BLOCK" as const,
  reason:
    "Regression against the baseline: answer_match dropped 0.83 (1.00 → 0.17), " +
    "beyond the 0.05 tolerance.",
  baseline_run_id: "baseline-run",
  baseline_run_name: "Release 1.2",
  metric_tolerance: 0.05,
  case_tolerance: 2,
  metric_deltas: [
    {
      name: "answer_match",
      baseline: 1,
      current: 0.17,
      delta: -0.83,
      passed_before: true,
      passed_now: false,
      hard_gate: false,
      regressed: true,
    },
  ],
  regressed_metrics: ["answer_match"],
  regressed_cases: [{ row_index: 3, input: "How do I reset my password?" }],
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("BaselinePanel", () => {
  it("shows how the run compares with the baseline it names", async () => {
    getBaselineMock.mockResolvedValue(BASELINE);
    render(<BaselinePanel run={makeRun({ regression: BLOCKED })} />);

    expect(await screen.findByTestId("baseline-current")).toHaveTextContent("Release 1.2");
    expect(screen.getByTestId("regression-status")).toHaveTextContent("Block");
    expect(screen.getByTestId("regression-reason")).toHaveTextContent("answer_match");
    expect(screen.getByTestId("regression-metrics")).toHaveTextContent("answer match");
    expect(screen.getByTestId("regression-metrics")).toHaveTextContent("-0.83");
    expect(screen.getByTestId("regression-cases")).toHaveTextContent("How do I reset my password?");
  });

  it("sets this run as the baseline and then shows it", async () => {
    getBaselineMock.mockResolvedValueOnce(null).mockResolvedValue(BASELINE);
    setBaselineMock.mockResolvedValue(BASELINE);
    getRunMock.mockResolvedValue(makeRun());

    render(<BaselinePanel run={makeRun()} />);

    const button = await screen.findByTestId("baseline-set");
    await userEvent.click(button);

    await waitFor(() => expect(setBaselineMock).toHaveBeenCalledWith("run-1"));
    expect(await screen.findByTestId("baseline-current")).toHaveTextContent("Release 1.2");
    expect(screen.queryByTestId("baseline-set")).not.toBeInTheDocument();
  });

  it("clears the baseline and offers to set one again", async () => {
    // This run is the baseline itself, then clearing leaves no baseline at all.
    getBaselineMock.mockResolvedValueOnce({ ...BASELINE, run_id: "run-1" }).mockResolvedValue(null);
    clearBaselineMock.mockResolvedValue(undefined);
    getRunMock.mockResolvedValue(makeRun());

    render(<BaselinePanel run={makeRun({ is_baseline: true })} />);

    expect(await screen.findByTestId("baseline-is-self")).toBeInTheDocument();
    await userEvent.click(screen.getByTestId("baseline-clear"));

    await waitFor(() => expect(clearBaselineMock).toHaveBeenCalledWith("run-1"));
    expect(await screen.findByTestId("baseline-set")).toBeInTheDocument();
  });

  it("shows the API's message when a run cannot be a baseline", async () => {
    getBaselineMock.mockResolvedValue(null);
    setBaselineMock.mockRejectedValue(
      new ApiError("Only a completed run can be a baseline.", 409, "conflict"),
    );

    render(<BaselinePanel run={makeRun()} />);

    await userEvent.click(await screen.findByTestId("baseline-set"));

    expect(await screen.findByTestId("baseline-error")).toHaveTextContent(
      "Only a completed run can be a baseline.",
    );
  });

  it("says nothing is comparable until the run finishes", () => {
    render(<BaselinePanel run={makeRun({ state: "running" })} />);

    expect(screen.getByTestId("baseline-panel")).toHaveTextContent(
      "A finished run can become this dataset version's baseline",
    );
    expect(screen.queryByTestId("baseline-set")).not.toBeInTheDocument();
    // No baseline lookup for a run that cannot be compared yet.
    expect(getBaselineMock).not.toHaveBeenCalled();
  });
});
