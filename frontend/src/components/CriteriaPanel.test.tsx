import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CriteriaPanel } from "./CriteriaPanel";
import { ApiError } from "../lib/api";
import type { CriteriaOverview } from "../lib/criteria";

const { getCriteriaMock } = vi.hoisted(() => ({ getCriteriaMock: vi.fn() }));

vi.mock("../lib/criteria", () => ({
  getCriteria: getCriteriaMock,
}));

function makeOverview(): CriteriaOverview {
  return {
    template: {
      key: "plain_chatbot",
      name: "Plain chatbot",
      description: "A prompt-only app with no retrieval.",
    },
    review_threshold: 0.6,
    go_threshold: 0.8,
    criteria: [
      {
        name: "answer_match",
        group: "quality",
        weight: 0.4,
        hard_gate: false,
        threshold: 0.6,
        gate_threshold: null,
        applies: "always",
      },
      {
        name: "output_nonempty",
        group: "quality",
        weight: 0.15,
        hard_gate: true,
        threshold: 1.0,
        gate_threshold: 1.0,
        applies: "always",
      },
      {
        name: "attack_resisted",
        group: "safety",
        weight: 0.2,
        hard_gate: true,
        threshold: 0.95,
        gate_threshold: 0.95,
        applies: "safety on",
      },
      {
        name: "error_rate",
        group: "operations",
        weight: 0.15,
        hard_gate: false,
        threshold: 0.9,
        gate_threshold: null,
        applies: "always",
      },
    ],
    rules: [
      { rule: 1, verdict: "NO_GO", text: "A hard gate failed: NO-GO." },
      { rule: 2, verdict: "NO_GO", text: "Below the REVIEW threshold: NO-GO." },
      { rule: 3, verdict: "REVIEW", text: "The judge was unsure: REVIEW." },
      { rule: 4, verdict: "REVIEW", text: "Between the thresholds: REVIEW." },
      { rule: 5, verdict: "GO", text: "At or above the GO threshold: GO." },
    ],
    not_instrumented_rule:
      "A metric the app never reported is left out and the average is renormalised; it is never counted as 0.",
    templates: [
      {
        key: "plain_chatbot",
        name: "Plain chatbot",
        description: "A prompt-only app.",
        criteria_count: 5,
      },
      {
        key: "rag_chatbot",
        name: "RAG chatbot",
        description: "Answers backed by context.",
        criteria_count: 7,
      },
    ],
    default_template_key: "plain_chatbot",
  };
}

describe("CriteriaPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getCriteriaMock.mockResolvedValue(makeOverview());
  });

  it("shows the thresholds as a No-Go / Review / Go scale", async () => {
    render(<CriteriaPanel />);

    await waitFor(() => expect(screen.getByTestId("criteria-thresholds")).toBeInTheDocument());
    const scale = screen.getByTestId("criteria-thresholds");
    expect(scale).toHaveTextContent("No-Go");
    expect(scale).toHaveTextContent("Review");
    expect(scale).toHaveTextContent("Go");
    // The numbers shown are the engine's, with their band wording.
    expect(scale).toHaveTextContent("below 0.60");
    expect(scale).toHaveTextContent("0.60–0.80");
    expect(scale).toHaveTextContent("from 0.80");
  });

  it("lists every metric with its weight, group and hard gate", async () => {
    render(<CriteriaPanel />);
    await waitFor(() => expect(screen.getByTestId("criteria-metrics")).toBeInTheDocument());

    const table = screen.getByTestId("criteria-metrics");
    expect(within(table).getAllByRole("row")).toHaveLength(5); // header + 4 metrics

    expect(screen.getByTestId("criteria-metric-answer_match")).toHaveTextContent("0.40");
    expect(screen.getByTestId("criteria-metric-answer_match")).toHaveTextContent("Quality");
    expect(screen.getByTestId("criteria-metric-answer_match")).toHaveTextContent("—");

    // A hard gate states its bar; over_refusal-style metrics do not.
    expect(screen.getByTestId("criteria-metric-output_nonempty")).toHaveTextContent(
      "hard gate at 1.00",
    );
    expect(screen.getByTestId("criteria-metric-attack_resisted")).toHaveTextContent(
      "hard gate at 0.95",
    );
    expect(screen.getByTestId("criteria-metric-attack_resisted")).toHaveTextContent("safety on");
    expect(screen.getByTestId("criteria-metric-error_rate")).toHaveTextContent("Operations");
  });

  it("shows the rules in order with their verdicts", async () => {
    render(<CriteriaPanel />);
    await waitFor(() => expect(screen.getByTestId("criteria-rules")).toBeInTheDocument());

    const rules = screen.getByTestId("criteria-rules");
    const items = within(rules).getAllByRole("listitem");
    expect(items).toHaveLength(5);
    expect(items[0]).toHaveTextContent("A hard gate failed");
    expect(items[1]).toHaveTextContent("Below the REVIEW threshold");
    expect(items[2]).toHaveTextContent("The judge was unsure");
    expect(items[3]).toHaveTextContent("Between the thresholds");
    expect(items[4]).toHaveTextContent("At or above the GO threshold");
    expect(items[0]).toHaveTextContent("No-Go");
    expect(items[2]).toHaveTextContent("Review");
    expect(items[4]).toHaveTextContent("Go");
  });

  it("explains that missing instrumentation is not a zero", async () => {
    render(<CriteriaPanel />);
    await waitFor(() =>
      expect(screen.getByTestId("criteria-not-instrumented")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("criteria-not-instrumented")).toHaveTextContent("never counted as 0");
    expect(screen.getByTestId("criteria-readonly-note")).toHaveTextContent(
      "Editing criteria is not supported yet",
    );
  });

  it("shows the API's error and retries", async () => {
    const user = userEvent.setup();
    getCriteriaMock.mockRejectedValueOnce(new ApiError("Could not load the criteria.", 500));
    render(<CriteriaPanel />);

    await waitFor(() => expect(screen.getByTestId("criteria-error")).toBeInTheDocument());
    expect(screen.getByTestId("criteria-error")).toHaveTextContent("Could not load the criteria.");

    await user.click(screen.getByTestId("criteria-retry"));
    await waitFor(() => expect(screen.getByTestId("criteria-thresholds")).toBeInTheDocument());
    expect(getCriteriaMock).toHaveBeenCalledTimes(2);
  });
});
