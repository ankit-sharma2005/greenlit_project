import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MetricBars } from "./MetricBars";
import type { MetricBar } from "../../lib/chartData";

function bar(overrides: Partial<MetricBar> = {}): MetricBar {
  return {
    name: "answer_match",
    label: "answer match",
    score: 0.75,
    measured: true,
    threshold: 0.6,
    hardGate: false,
    passed: true,
    weight: 0.3,
    ...overrides,
  };
}

describe("MetricBars", () => {
  it("draws one bar per measured metric and a tick for each hard gate", () => {
    render(
      <MetricBars
        bars={[
          bar({ name: "answer_match", score: 0.75, passed: true }),
          bar({ name: "output_nonempty", score: 0.9, weight: 0.1, hardGate: true, threshold: 1 }),
          bar({ name: "error_rate", score: 0.4, passed: false, threshold: 0.9, weight: 0.1 }),
        ]}
      />,
    );

    expect(screen.getByTestId("metric-bar-answer_match")).toBeInTheDocument();
    expect(screen.getByTestId("metric-bar-output_nonempty")).toBeInTheDocument();
    expect(screen.getByTestId("metric-bar-error_rate")).toBeInTheDocument();
    expect(screen.queryByTestId("metric-gate-answer_match")).not.toBeInTheDocument();
    expect(screen.getByTestId("metric-gate-output_nonempty")).toBeInTheDocument();
    const svg = screen.getByTestId("metric-bars-svg");
    expect(svg).toHaveAttribute("role", "img");
    expect(svg.getAttribute("aria-label")).toContain("answer match 0.75");
    expect(svg).toHaveTextContent("0.40 fail");
  });

  it("shows an unmeasured metric as a labelled empty slot, never as a zero bar", () => {
    render(
      <MetricBars
        bars={[
          bar({ name: "answer_match" }),
          bar({
            name: "retrieval_context_recall",
            label: "retrieval context recall",
            score: null,
            measured: false,
            passed: null,
            weight: 0.25,
          }),
        ]}
      />,
    );

    expect(screen.queryByTestId("metric-bar-retrieval_context_recall")).not.toBeInTheDocument();
    expect(screen.getByTestId("metric-unmeasured-retrieval_context_recall")).toBeInTheDocument();
    const svg = screen.getByTestId("metric-bars-svg");
    expect(svg).toHaveTextContent("not measured");
    expect(svg.getAttribute("aria-label")).toContain("retrieval context recall not measured");
    expect(svg).not.toHaveTextContent("retrieval context recall 0.00");
  });

  it("carries the plotted numbers into the data table", () => {
    render(
      <MetricBars
        bars={[
          bar({ name: "answer_match", score: 0.75, weight: 0.3 }),
          bar({
            name: "tool_call_match",
            label: "tool call match",
            score: null,
            measured: false,
            passed: null,
            weight: 0.2,
          }),
        ]}
      />,
    );

    const table = screen.getByTestId("metric-bars-table");
    expect(table).toHaveTextContent("answer match");
    expect(table).toHaveTextContent("0.75");
    expect(table).toHaveTextContent("tool call match");
    expect(table).toHaveTextContent("not measured");
  });
});
