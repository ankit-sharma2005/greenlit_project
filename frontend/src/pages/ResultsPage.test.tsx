import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PreviewResponse } from "../lib/evaluations";
import { ResultsPage } from "./ResultsPage";

const mocks = vi.hoisted(() => ({
  listTemplates: vi.fn(),
  previewEvaluation: vi.fn(),
}));

vi.mock("../lib/evaluations", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/evaluations")>();
  return {
    ...actual,
    listTemplates: mocks.listTemplates,
    previewEvaluation: mocks.previewEvaluation,
  };
});

const TEMPLATES = {
  templates: [
    {
      key: "rag_chatbot",
      name: "RAG chatbot",
      description: "Answers backed by retrieved context.",
      review_threshold: 0.6,
      go_threshold: 0.8,
      criteria: [
        { metric: "answer_match", weight: 0.3, threshold: 0.6, hard_gate: false },
      ],
    },
    {
      key: "plain_chatbot",
      name: "Plain chatbot",
      description: "No retrieval.",
      review_threshold: 0.6,
      go_threshold: 0.8,
      criteria: [
        { metric: "answer_match", weight: 0.4, threshold: 0.6, hard_gate: false },
      ],
    },
  ],
  default: "rag_chatbot",
};

const BROKEN: PreviewResponse = {
  profile: "rag_chatbot",
  profile_name: "RAG chatbot",
  verdict: "NO_GO",
  score: 0.39,
  rule: 2,
  reason:
    "Weighted score 0.39 is below the REVIEW threshold 0.60. Weakest metrics: answer_match 0.00, retrieval_context_recall 0.00.",
  review_threshold: 0.6,
  go_threshold: 0.8,
  suggested_fixes: [
    "retrieval recall is low: check chunking, top-k and the embedding model",
    "answers do not contain the expected facts: check the prompt, the model and the retrieval step",
  ],
  metrics: [
    {
      name: "answer_match",
      score: 0,
      passed: false,
      explanation: "3 of 3 measured cases passed; average score 0.00",
      instrumented: true,
      weight: 0.3,
      threshold: 0.6,
      hard_gate: false,
      details: {},
    },
    {
      name: "retrieval_context_recall",
      score: 0,
      passed: false,
      explanation: "retrieval found 0 of 9 content words the correct context needs",
      instrumented: true,
      weight: 0.25,
      threshold: 0.6,
      hard_gate: false,
      details: {},
    },
    {
      name: "token_usage_present",
      score: 0,
      passed: false,
      explanation: "not instrumented: the app does not report token usage",
      instrumented: false,
      weight: 0.05,
      threshold: 0.9,
      hard_gate: false,
      details: {},
    },
    {
      name: "latency_under_limit",
      score: 0.8,
      passed: false,
      explanation: "3 of 3 answers arrived",
      instrumented: true,
      weight: 0.15,
      threshold: 0.9,
      hard_gate: false,
      details: { p50_ms: 9000, p95_ms: 9400 },
    },
  ],
  failed_cases: [
    {
      input: "What does the Merit Scholarship cover?",
      expected: "The Merit Scholarship covers full tuition and fees for four years.",
      actual: "I am not sure about that.",
      reason:
        "answer_match: the answer shares no content words with the expected answer; retrieval_context_recall: retrieval found 0 of 9 content words",
    },
  ],
  item_count: 3,
  valid_items: 3,
};

describe("ResultsPage", () => {
  beforeEach(() => {
    mocks.listTemplates.mockReset().mockResolvedValue(TEMPLATES);
    mocks.previewEvaluation.mockReset().mockResolvedValue(BROKEN);
  });

  it("loads the criteria templates into the profile select", async () => {
    render(<ResultsPage />);

    expect(await screen.findByRole("option", { name: "RAG chatbot" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Plain chatbot" })).toBeInTheDocument();
  });

  it("shows the verdict, score, reason, metric table and failed cases", async () => {
    render(<ResultsPage />);
    await screen.findByRole("option", { name: "RAG chatbot" });

    await userEvent.click(screen.getByRole("button", { name: "Load broken example" }));
    await userEvent.click(screen.getByTestId("evaluate-button"));

    await waitFor(() => expect(screen.getByTestId("verdict-word")).toHaveTextContent("No-Go"));
    expect(screen.getByTestId("verdict-score")).toHaveTextContent("0.39");
    expect(screen.getByTestId("verdict-thresholds")).toHaveTextContent("REVIEW 0.60");
    expect(screen.getByTestId("verdict-reason")).toHaveTextContent("REVIEW threshold 0.60");
    expect(screen.getByTestId("suggested-fixes")).toHaveTextContent("retrieval recall is low");

    const metrics = screen.getByTestId("metrics-table");
    expect(metrics).toHaveTextContent("answer match");
    expect(metrics).toHaveTextContent("not instrumented");
    expect(metrics).toHaveTextContent("fail");

    const failed = screen.getByTestId("failed-cases");
    expect(failed).toHaveTextContent("What does the Merit Scholarship cover?");
    expect(failed).toHaveTextContent("I am not sure about that.");
  });

  it("sends the selected profile and the pasted outputs", async () => {
    render(<ResultsPage />);
    await screen.findByRole("option", { name: "Plain chatbot" });

    await userEvent.selectOptions(screen.getByTestId("criteria-profile"), "plain_chatbot");
    await userEvent.click(screen.getByRole("button", { name: "Load good example" }));
    await userEvent.click(screen.getByTestId("evaluate-button"));

    await waitFor(() => expect(mocks.previewEvaluation).toHaveBeenCalledTimes(1));
    const [argument] = mocks.previewEvaluation.mock.calls[0] as [
      { profile: string; csv: string },
    ];
    expect(argument.profile).toBe("plain_chatbot");
    expect(argument.csv).toContain("input,expected_answer,output");
  });

  it("explains an empty submission instead of calling the API", async () => {
    render(<ResultsPage />);
    await screen.findByRole("option", { name: "RAG chatbot" });

    await userEvent.click(screen.getByTestId("evaluate-button"));

    expect(await screen.findByRole("alert")).toHaveTextContent("Paste the app's outputs first");
    expect(mocks.previewEvaluation).not.toHaveBeenCalled();
  });
});
