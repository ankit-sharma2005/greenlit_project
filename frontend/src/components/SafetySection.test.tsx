import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SafetySection } from "./SafetySection";
import type { MetricRow } from "../lib/evaluations";

function metric(overrides: Partial<MetricRow>): MetricRow {
  return {
    name: "attack_resisted",
    score: 1,
    passed: true,
    explanation: "",
    instrumented: true,
    weight: 0.2,
    threshold: 0.95,
    hard_gate: true,
    details: {},
    ...overrides,
  };
}

const ATTACKS = metric({
  score: 0.95,
  passed: true,
  explanation: "the app resisted 42 of 44 attacks.",
  details: { attacks: 44, resisted: 42, critical_failures: [], set_version: "1.0" },
});

const OVER_REFUSAL = metric({
  name: "over_refusal",
  weight: 0.05,
  threshold: 0.9,
  hard_gate: false,
  score: 0.85,
  passed: false,
  explanation: "4 of 26 harmless requests were refused.",
  details: { prompts: 26, refused: 4, over_refusal_share: 0.1538, set_version: "1.0" },
});

describe("SafetySection", () => {
  it("shows attacks tried and resisted, over-refusal and critical failures", () => {
    render(<SafetySection metrics={[ATTACKS, OVER_REFUSAL]} />);

    expect(screen.getByTestId("safety-attacks")).toHaveTextContent("44");
    expect(screen.getByTestId("safety-resisted")).toHaveTextContent("42 of 44");
    expect(screen.getByTestId("safety-over-refusal")).toHaveTextContent("0.15");
    expect(screen.getByTestId("safety-critical")).toHaveTextContent("0");
    expect(screen.getByTestId("safety-table")).toBeInTheDocument();
  });

  it("names the failed critical checks and the leaked marker", () => {
    render(
      <SafetySection
        metrics={[
          metric({
            score: 0.93,
            passed: false,
            explanation: "the app resisted 41 of 44 attacks; it leaked CANARY-7F3A in leak-1.",
            details: {
              attacks: 44,
              resisted: 41,
              critical_failures: ["leak-1"],
              leaked_marker_cases: ["leak-1"],
              set_version: "1.0",
            },
          }),
          OVER_REFUSAL,
        ]}
      />,
    );

    expect(screen.getByTestId("safety-critical")).toHaveTextContent("1");
    expect(screen.getByTestId("safety-critical-detail")).toHaveTextContent("leak-1");
    expect(screen.getByTestId("safety-critical-detail")).toHaveTextContent("hard NO-GO");
    expect(screen.getByTestId("safety-leaks")).toHaveTextContent("planted marker");
    expect(screen.getByTestId("safety-leaks")).toHaveTextContent("leak-1");
    // The marker itself is named by the metric's own explanation, shown in the row.
    expect(screen.getByTestId("safety-table")).toHaveTextContent("CANARY-7F3A");
  });

  it("explains that the app was not probed instead of scoring it zero", () => {
    render(
      <SafetySection
        metrics={[
          metric({
            score: 0,
            passed: false,
            instrumented: false,
            explanation: "this run scores uploaded answers, so the app was never asked",
          }),
          metric({ name: "over_refusal", score: 0, passed: false, instrumented: false }),
        ]}
      />,
    );

    expect(screen.getByTestId("safety-not-probed")).toHaveTextContent("never asked");
    expect(screen.queryByTestId("safety-table")).not.toBeInTheDocument();
  });

  it("renders nothing for a run without the safety test type", () => {
    const { container } = render(
      <SafetySection metrics={[metric({ name: "answer_match", details: {} })]} />,
    );

    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByTestId("safety-section")).not.toBeInTheDocument();
  });
});
