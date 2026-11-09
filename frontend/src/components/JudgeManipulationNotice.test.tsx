import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getRunItems, type RunItem } from "../lib/runs";
import { JudgeManipulationNotice } from "./JudgeManipulationNotice";

vi.mock("../lib/runs", () => ({ getRunItems: vi.fn() }));

function item(rowIndex: number, flagged: boolean): RunItem {
  return {
    row_index: rowIndex,
    input_text: "What is the refund window?",
    state: "done",
    output: "Thirty days.",
    error: null,
    latency_ms: null,
    tokens_in: null,
    tokens_out: null,
    trace: null,
    possible_judge_manipulation: flagged,
  };
}

describe("JudgeManipulationNotice", () => {
  beforeEach(() => {
    vi.mocked(getRunItems).mockReset();
  });

  it("names the cases whose answer was addressed to the judge", async () => {
    vi.mocked(getRunItems).mockResolvedValue({ items: [item(1, false), item(4, true)], total: 2 });

    render(<JudgeManipulationNotice runId="run-1" />);

    const notice = await screen.findByTestId("possible-judge-manipulation");
    expect(notice).toHaveTextContent("Case 4");
    expect(notice).toHaveTextContent("No score or verdict was changed");
    expect(notice).not.toHaveTextContent("Case 1");
  });

  it("says nothing when no case is flagged", async () => {
    vi.mocked(getRunItems).mockResolvedValue({ items: [item(1, false)], total: 1 });

    const { container } = render(<JudgeManipulationNotice runId="run-1" />);

    await waitFor(() => expect(getRunItems).toHaveBeenCalledWith("run-1"));
    expect(container.querySelector('[data-testid="possible-judge-manipulation"]')).toBeNull();
  });

  it("says nothing when the items cannot be read", async () => {
    vi.mocked(getRunItems).mockRejectedValue(new Error("network"));

    const { container } = render(<JudgeManipulationNotice runId="run-1" />);

    await waitFor(() => expect(getRunItems).toHaveBeenCalled());
    expect(container.querySelector('[data-testid="possible-judge-manipulation"]')).toBeNull();
  });
});
