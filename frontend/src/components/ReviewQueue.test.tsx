import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewQueue } from "./ReviewQueue";
import { ApiError } from "../lib/api";
import type { ReviewCase } from "../lib/labels";

const { listReviewQueueMock, saveLabelMock } = vi.hoisted(() => ({
  listReviewQueueMock: vi.fn(),
  saveLabelMock: vi.fn(),
}));

vi.mock("../lib/labels", () => ({
  listReviewQueue: listReviewQueueMock,
  saveLabel: saveLabelMock,
}));

const CASE: ReviewCase = {
  run_item_id: "item-1",
  run_id: "run-1",
  run_name: "Judged run",
  row_index: 2,
  input_text: "How do I reset my password?",
  output: "Use the reset link.",
  judge_score: null,
  judge_bucket: null,
  judge_confidence: null,
  judge_reason: "the judge was unavailable",
  reasons: ["the judge could not score this case"],
  label: null,
  note: null,
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ReviewQueue", () => {
  it("lists the cases with the reason the judge could not settle them", async () => {
    listReviewQueueMock.mockResolvedValue({ items: [CASE], total: 1 });

    render(<ReviewQueue />);

    expect(await screen.findByTestId("review-table")).toHaveTextContent(
      "How do I reset my password?",
    );
    expect(screen.getByTestId("review-row")).toHaveTextContent(
      "the judge could not score this case",
    );
    expect(screen.getByTestId("review-row")).toHaveTextContent("the judge was unavailable");
  });

  it("saves approve and reject with the note, then shows the case is labelled", async () => {
    listReviewQueueMock
      .mockResolvedValueOnce({ items: [CASE], total: 1 })
      .mockResolvedValueOnce({ items: [{ ...CASE, label: "fail" }], total: 1 });
    saveLabelMock.mockResolvedValue({ id: "label-1", label: "fail" });
    const onLabelled = vi.fn();

    render(<ReviewQueue onLabelled={onLabelled} />);

    await userEvent.type(await screen.findByTestId("review-note"), "The fact is wrong");
    await userEvent.click(screen.getByTestId("review-fail"));

    await waitFor(() =>
      expect(saveLabelMock).toHaveBeenCalledWith("item-1", "fail", "The fact is wrong"),
    );
    expect(await screen.findByTestId("review-label")).toHaveTextContent("labelled fail");
    expect(onLabelled).toHaveBeenCalledTimes(1);
  });

  it("says the queue is clear when nothing needs review", async () => {
    listReviewQueueMock.mockResolvedValue({ items: [], total: 0 });

    render(<ReviewQueue />);

    expect(await screen.findByTestId("review-empty")).toHaveTextContent("No cases need review");
    expect(screen.queryByTestId("review-table")).not.toBeInTheDocument();
  });

  it("shows the API's message when the queue cannot be read", async () => {
    listReviewQueueMock.mockRejectedValue(
      new ApiError("Your role does not allow this action.", 403, "forbidden"),
    );

    render(<ReviewQueue />);

    expect(await screen.findByTestId("review-error")).toHaveTextContent(
      "Your role does not allow this action.",
    );
  });
});
