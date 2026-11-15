import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RegressionCompare } from "./RegressionCompare";
import type { CompareDetail } from "../lib/baselines";

const { getCompareMock } = vi.hoisted(() => ({ getCompareMock: vi.fn() }));

vi.mock("../lib/baselines", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/baselines")>();
  return { ...actual, getCompare: getCompareMock };
});

function detail(overrides: Partial<CompareDetail> = {}): CompareDetail {
  return {
    comparable: true,
    reasons: [],
    baseline_run_id: "baseline-1",
    baseline_run_name: "Release 1.2",
    current_run_id: "run-1",
    current_run_name: "Nightly",
    tolerance: 0.05,
    deterministic_target: false,
    noise_caution:
      "This target is model-backed, so a few flipped cases can be run-to-run noise. " +
      "Repeat the run before concluding that the app regressed; this comparison cannot " +
      "tell a real change from sampling luck.",
    verdict: { baseline: "GO", current: "REVIEW", direction: "worse" },
    verdict_changed: true,
    score: { baseline: 0.9, current: 0.8, delta: -0.1 },
    classification: "regressed",
    classification_reason: "the verdict went GO → REVIEW; the score dropped 0.10, beyond 0.05.",
    existing_status: "BLOCK",
    metrics: [
      {
        name: "answer_match",
        status: "measured",
        baseline: 0.9,
        current: 0.8,
        delta: -0.1,
        passed_before: true,
        passed_now: true,
        hard_gate: false,
      },
      {
        name: "groundedness",
        status: "not measured",
        baseline: null,
        current: null,
        delta: null,
        passed_before: null,
        passed_now: null,
        hard_gate: false,
      },
    ],
    hard_gates: { newly_failed: ["attack_resisted"], newly_passed: [] },
    latency: {
      baseline: { p50: 200, p95: 290, samples: 2 },
      current: { p50: 300, p95: 390, samples: 2 },
      delta: { p50: 100, p95: 100 },
    },
    cases: {
      pass_to_fail: [
        { row_index: 1, input:
          "What is 155 + 332? A deliberately long question that runs past the truncation rule of this block.", },
      ],
      fail_to_pass: [],
      new_errors: [],
      only_in_baseline: [],
      only_in_current: [],
    },
    ...overrides,
  };
}

function renderBlock() {
  return render(
    <MemoryRouter>
      <RegressionCompare runId="run-1" baselineName="Release 1.2" />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  getCompareMock.mockResolvedValue(detail());
});

describe("RegressionCompare", () => {
  it("shows the regressed classification, verdict, score and flipped case", async () => {
    renderBlock();

    await waitFor(() => expect(screen.getByTestId("compare-class-regressed")).toBeInTheDocument());
    expect(screen.getByTestId("compare-class-regressed")).toHaveTextContent("Regressed");
    expect(screen.getByTestId("compare-verdict")).toHaveTextContent("GO → REVIEW (worse)");
    expect(screen.getByTestId("compare-score")).toHaveTextContent("-0.10");
    expect(screen.getByTestId("compare-hard-gates")).toHaveTextContent("attack_resisted");
    expect(screen.getByTestId("compare-flip-1")).toHaveTextContent("…");
    expect(screen.getByTestId("compare-noise")).toHaveTextContent("Repeat the run");
    expect(screen.getByTestId("compare-existing-status")).toHaveTextContent("BLOCK");
  });

  it("never shows a delta for a metric that was not measured on both sides", async () => {
    renderBlock();

    await waitFor(() => expect(screen.getByTestId("compare-metrics")).toBeInTheDocument());
    const rows = screen.getAllByRole("row");
    const unmeasured = rows.find((row) => row.textContent?.includes("groundedness"));
    expect(unmeasured).toBeDefined();
    expect(unmeasured?.textContent).toContain("not measured");
    expect(unmeasured?.textContent).not.toContain("0.00");
    expect(screen.getByTestId("compare-unmeasured")).toHaveTextContent("groundedness");
  });

  it("shows the reasons and no numbers when the runs are not comparable", async () => {
    getCompareMock.mockResolvedValue(
      detail({
        comparable: false,
        reasons: ["the dataset version is different", "the test types are different (quality vs quality, safety)"],
        classification: null,
        classification_reason: null,
        metrics: [],
        hard_gates: { newly_failed: [], newly_passed: [] },
        noise_caution: null,
      }),
    );
    renderBlock();

    await waitFor(() => expect(screen.getByTestId("compare-not-comparable")).toBeInTheDocument());
    expect(screen.getByTestId("compare-reasons")).toHaveTextContent("dataset version");
    expect(screen.queryByTestId("compare-metrics")).not.toBeInTheDocument();
    expect(screen.queryByTestId("compare-class-regressed")).not.toBeInTheDocument();
  });

  it("shows unchanged therefore without a flip list or a caution on a deterministic target", async () => {
    getCompareMock.mockResolvedValue(
      detail({
        classification: "unchanged",
        classification_reason: "Nothing moved beyond the tolerance in either direction.",
        verdict: { baseline: "GO", current: "GO", direction: "same" },
        score: { baseline: 0.9, current: 0.9, delta: 0 },
        existing_status: "PASS",
        metrics: [],
        hard_gates: { newly_failed: [], newly_passed: [] },
        cases: {
          pass_to_fail: [],
          fail_to_pass: [],
          new_errors: [],
          only_in_baseline: [],
          only_in_current: [],
        },
        deterministic_target: true,
        noise_caution: null,
      }),
    );
    renderBlock();

    await waitFor(() =>
      expect(screen.getByTestId("compare-class-unchanged")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("compare-flips")).not.toBeInTheDocument();
    expect(screen.queryByTestId("compare-noise")).not.toBeInTheDocument();
  });
});
