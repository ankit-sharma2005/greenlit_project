import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LatencyChart } from "./LatencyChart";

const SUMMARY = {
  samples: 4,
  p50: 250,
  p95: 385,
  slowest: [
    { row: 4, latencyMs: 400 },
    { row: 3, latencyMs: 300 },
  ],
};

describe("LatencyChart", () => {
  it("draws only the measured cases with the p50 and p95 written above them", () => {
    render(<LatencyChart summary={SUMMARY} />);

    const svg = screen.getByTestId("latency-chart-svg");
    expect(svg).toHaveAttribute("role", "img");
    expect(svg.getAttribute("aria-label")).toContain("Latency of 4 measured cases");
    expect(svg.getAttribute("aria-label")).toContain("p50 250 ms, p95 385 ms");
    expect(svg).toHaveTextContent("p50 250 ms · p95 385 ms");
    expect(screen.getByTestId("latency-bar-4")).toBeInTheDocument();
    expect(screen.getByTestId("latency-bar-3")).toBeInTheDocument();
    expect(screen.queryByTestId("latency-bar-0")).not.toBeInTheDocument();
  });

  it("states the percentile method and the sample count in the description", () => {
    render(<LatencyChart summary={SUMMARY} />);
    expect(screen.getByTestId("latency-chart")).toHaveTextContent(
      "linear interpolation between the two closest ranks",
    );
    expect(screen.getByTestId("latency-chart")).toHaveTextContent("4 cases that reported a latency");
  });

  it("shows the optional limit when one is given", () => {
    render(<LatencyChart summary={SUMMARY} limitMs={3000} />);
    expect(screen.getByTestId("latency-chart-svg")).toHaveTextContent("limit 3000 ms");
  });

  it("carries the plotted numbers into the data table", () => {
    render(<LatencyChart summary={SUMMARY} />);
    const table = screen.getByTestId("latency-chart-table");
    expect(table).toHaveTextContent("p50");
    expect(table).toHaveTextContent("250 ms");
    expect(table).toHaveTextContent("p95");
    expect(table).toHaveTextContent("385 ms");
    expect(table).toHaveTextContent("Case 5");
    expect(table).toHaveTextContent("400 ms");
  });
});
