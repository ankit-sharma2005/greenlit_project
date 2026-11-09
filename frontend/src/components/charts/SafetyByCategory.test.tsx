import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SafetyByCategory } from "./SafetyByCategory";
import type { SafetyCategory } from "../../lib/chartData";

function category(overrides: Partial<SafetyCategory> = {}): SafetyCategory {
  return {
    id: "system_prompt_leak",
    name: "System prompt leaks",
    cases: 8,
    leaked: 2,
    noLeak: 6,
    criticalFailures: 1,
    criticalCases: 3,
    ...overrides,
  };
}

describe("SafetyByCategory", () => {
  it("draws one stacked pair per category with the counts beside it", () => {
    render(
      <SafetyByCategory
        categories={[
          category(),
          category({ id: "direct_injection", name: "Direct injection", cases: 10, leaked: 0, noLeak: 10, criticalFailures: 0, criticalCases: 0 }),
        ]}
      />,
    );

    expect(screen.getByTestId("safety-safebar-system_prompt_leak")).toBeInTheDocument();
    expect(screen.getByTestId("safety-leakedbar-system_prompt_leak")).toBeInTheDocument();
    expect(screen.getByTestId("safety-safebar-direct_injection")).toBeInTheDocument();
    const svg = screen.getByTestId("safety-by-category-svg");
    expect(svg).toHaveAttribute("role", "img");
    expect(svg.getAttribute("aria-label")).toContain(
      "System prompt leaks: 8 attacks, 2 leaked, 1 critical failure",
    );
    expect(svg).toHaveTextContent("6 no leak · 2 leaked");
    // The legend names both sides, so the hatch pattern is never the only signal.
    expect(svg).toHaveTextContent("no leak recorded");
    expect(svg).toHaveTextContent("leaked");
  });

  it("draws a zero-width leak segment for a category with no leak instead of omitting it", () => {
    render(<SafetyByCategory categories={[category({ leaked: 0, noLeak: 10, cases: 10 })]} />);
    expect(screen.getByTestId("safety-leakedbar-system_prompt_leak")).toBeInTheDocument();
    expect(screen.getByTestId("safety-leakedbar-system_prompt_leak")).toHaveAttribute("width", "0");
    expect(screen.getByTestId("safety-safebar-system_prompt_leak")).toHaveAttribute("width", "150");
  });

  it("renders nothing when safety never ran", () => {
    const { container } = render(<SafetyByCategory categories={[]} />);
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByTestId("safety-by-category")).not.toBeInTheDocument();
  });

  it("carries the plotted numbers into the data table", () => {
    render(<SafetyByCategory categories={[category()]} />);
    const table = screen.getByTestId("safety-by-category-table");
    expect(table).toHaveTextContent("System prompt leaks");
    expect(table).toHaveTextContent("8");
    expect(table).toHaveTextContent("6");
    expect(table).toHaveTextContent("2");
    expect(table).toHaveTextContent("1 critical failure");
  });
});
