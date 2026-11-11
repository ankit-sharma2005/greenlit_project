import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RunSummary } from "./RunSummary";
import type { RunSummary as RunSummaryData } from "../lib/runs";

const REVIEW: RunSummaryData = {
  headline:
    "GreenLit says REVIEW: the weighted score was 0.72, between the 0.60 review and 0.80 go thresholds.",
  reasons: ["The judge was unsure on 2 case(s), so a person should read them."],
  weakest: [{ metric: "answer_match", label: "answer match", score: 0.62 }],
  weakest_sentence: "Weakest measured metrics: answer match 0.62.",
  not_measured: ["retrieval context recall"],
  not_measured_sentence:
    "Not measured on this run: retrieval context recall. It is left out of the weighted score and not counted as zero.",
  safety_sentence: "Safety: no leak was recorded in 0 of 8 attack cases.",
  next_steps: [
    "answers do not contain the expected facts: check the prompt, the model and the retrieval step",
    "Read the cases the judge was unsure about before trusting the verdict.",
  ],
};

describe("RunSummary", () => {
  it("shows the headline, the reason and what to try next", () => {
    render(<RunSummary summary={REVIEW} />);

    expect(screen.getByRole("heading", { name: "In plain words" })).toBeInTheDocument();
    expect(screen.getByTestId("run-summary-headline")).toHaveTextContent(
      "GreenLit says REVIEW: the weighted score was 0.72",
    );
    expect(screen.getByTestId("run-summary-reasons")).toHaveTextContent(
      "The judge was unsure on 2 case(s)",
    );
    expect(screen.getByTestId("run-summary-next")).toHaveTextContent(
      "Read the cases the judge was unsure about",
    );
  });

  it("names an unmeasured metric without giving it a score", () => {
    render(<RunSummary summary={REVIEW} />);

    const line = screen.getByTestId("run-summary-not-measured");
    expect(line).toHaveTextContent("retrieval context recall");
    expect(line).not.toHaveTextContent("0.00");
    expect(line.textContent).not.toMatch(/retrieval context recall[^.]*\d\.\d\d/);
  });

  it("reports safety as counted cases, never as a pass", () => {
    render(<RunSummary summary={REVIEW} />);

    const safety = screen.getByTestId("run-summary-safety");
    expect(safety).toHaveTextContent("no leak was recorded in 0 of 8 attack cases");
    expect(safety.textContent?.toLowerCase()).not.toContain("passed");
  });
});
