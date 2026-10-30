import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { OperationsPanel } from "./OperationsPanel";
import type { RunOperations } from "../lib/runs";

function makeOperations(overrides: Partial<RunOperations> = {}): RunOperations {
  return {
    items_total: 4,
    items_attempted: 4,
    items_failed: 1,
    items_cancelled: 0,
    latency_samples: 4,
    latency_p50_ms: 210,
    latency_p95_ms: 480,
    error_rate: 0.25,
    timeout_rate: 0.25,
    items_timed_out: 1,
    tokens_in_total: 1500,
    tokens_out_total: 600,
    price_per_1k_tokens_in: null,
    price_per_1k_tokens_out: null,
    cost_configured: false,
    cost_estimate: null,
    ...overrides,
  };
}

describe("OperationsPanel", () => {
  it("renders latency percentiles, rates and token totals", () => {
    render(<OperationsPanel operations={makeOperations()} />);

    expect(screen.getByTestId("run-operations")).toBeInTheDocument();
    expect(screen.getByTestId("ops-p50")).toHaveTextContent("210 ms");
    expect(screen.getByTestId("ops-p95")).toHaveTextContent("480 ms");
    expect(screen.getByTestId("ops-error-rate")).toHaveTextContent("25.0%");
    expect(screen.getByTestId("ops-timeout-rate")).toHaveTextContent("25.0%");
    expect(screen.getByTestId("ops-tokens-in")).toHaveTextContent("1,500");
    expect(screen.getByTestId("ops-tokens-out")).toHaveTextContent("600");
  });

  it('shows "not configured" for cost when no prices are set', () => {
    render(<OperationsPanel operations={makeOperations()} />);

    expect(screen.getByTestId("ops-cost")).toHaveTextContent("not configured");
  });

  it("shows the estimated cost when prices are configured", () => {
    render(
      <OperationsPanel
        operations={makeOperations({
          cost_configured: true,
          cost_estimate: 0.027,
          price_per_1k_tokens_in: 0.01,
          price_per_1k_tokens_out: 0.02,
        })}
      />,
    );

    expect(screen.getByTestId("ops-cost")).toHaveTextContent("$0.0270");
  });

  it("says not measured instead of showing a zero for missing values", () => {
    render(
      <OperationsPanel
        operations={makeOperations({
          latency_samples: 0,
          latency_p50_ms: null,
          latency_p95_ms: null,
          error_rate: null,
          timeout_rate: null,
          tokens_in_total: null,
          tokens_out_total: null,
        })}
      />,
    );

    expect(screen.getByTestId("ops-p50")).toHaveTextContent("not measured");
    expect(screen.getByTestId("ops-p95")).toHaveTextContent("not measured");
    expect(screen.getByTestId("ops-error-rate")).toHaveTextContent("not measured");
    expect(screen.getByTestId("ops-timeout-rate")).toHaveTextContent("not measured");
    expect(screen.getByTestId("ops-tokens-in")).toHaveTextContent("not reported");
    expect(screen.getByTestId("ops-tokens-out")).toHaveTextContent("not reported");
    // The sample count line is omitted when nothing was measured.
    expect(screen.queryByTestId("ops-samples")).not.toBeInTheDocument();
  });

  it("renders nothing when the run has no operations block", () => {
    const { container } = render(<OperationsPanel operations={null} />);

    expect(container).toBeEmptyDOMElement();
  });
});
