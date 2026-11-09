import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RunTrend } from "./RunTrend";
import type { TrendRun } from "../../lib/chartData";

const THRESHOLDS = { review: 0.6, go: 0.8 };

function run(overrides: Partial<TrendRun> = {}): TrendRun {
  return {
    id: "r1",
    name: "Golden set",
    created_at: "2026-11-01T10:00:00Z",
    score: 0.9,
    verdict: "GO",
    ...overrides,
  };
}

describe("RunTrend", () => {
  it("asks for another run instead of drawing a line with one point", () => {
    render(<RunTrend runs={[run()]} thresholds={THRESHOLDS} />);
    expect(screen.getByTestId("run-trend-empty")).toHaveTextContent(
      "Two finished runs are needed to draw a trend.",
    );
    expect(screen.queryByTestId("run-trend-svg")).not.toBeInTheDocument();
  });

  it("draws one point per finished run, oldest first", () => {
    render(
      <RunTrend
        runs={[
          run({ id: "b", name: "Second", created_at: "2026-11-03T10:00:00Z", score: 0.5, verdict: "NO_GO" }),
          run({ id: "a", name: "First", created_at: "2026-11-01T10:00:00Z", score: 0.9, verdict: "GO" }),
        ]}
        thresholds={THRESHOLDS}
      />,
    );

    const svg = screen.getByTestId("run-trend-svg");
    expect(svg).toHaveAttribute("role", "img");
    expect(svg.getAttribute("aria-label")).toContain("0.90 Go, 0.50 No-Go");
    expect(screen.getByTestId("run-trend-point-0")).toBeInTheDocument();
    expect(screen.getByTestId("run-trend-point-1")).toBeInTheDocument();
    // Verdicts are named in the text, not only coloured.
    expect(svg).toHaveTextContent("GO 0.80");
    expect(svg).toHaveTextContent("REVIEW 0.60");
  });

  it("does not draw an unscored run as a point", () => {
    render(
      <RunTrend
        runs={[
          run({ id: "a" }),
          run({ id: "b", created_at: "2026-11-02T10:00:00Z", score: null, verdict: null }),
          run({ id: "c", created_at: "2026-11-03T10:00:00Z", score: 0.7, verdict: "REVIEW" }),
        ]}
        thresholds={THRESHOLDS}
      />,
    );
    expect(screen.getByTestId("run-trend-svg")).toHaveAttribute(
      "aria-label",
      expect.stringContaining("Scores of 2 finished runs"),
    );
  });

  it("carries the plotted numbers into the data table", () => {
    render(
      <RunTrend
        runs={[
          run({ id: "a", name: "First", score: 0.9, verdict: "GO" }),
          run({
            id: "b",
            name: "Second",
            created_at: "2026-11-03T10:00:00Z",
            score: 0.55,
            verdict: "NO_GO",
          }),
        ]}
        thresholds={THRESHOLDS}
      />,
    );
    const table = screen.getByTestId("run-trend-table");
    expect(table).toHaveTextContent("First");
    expect(table).toHaveTextContent("0.90");
    expect(table).toHaveTextContent("Second");
    expect(table).toHaveTextContent("0.55");
    expect(table).toHaveTextContent("No-Go");
  });
});
