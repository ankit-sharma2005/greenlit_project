import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ANSWER_PREVIEW_CHARS, AnswerCell } from "./RunProgressPanel";

const LONG = `${"a".repeat(ANSWER_PREVIEW_CHARS)}THIS-IS-THE-END`;

describe("AnswerCell", () => {
  it("shows a long answer whole when the account asked for full answers", () => {
    render(<AnswerCell answer={LONG} full />);

    expect(screen.getByText(LONG)).toBeInTheDocument();
    expect(screen.queryByTestId("answer-show-more")).not.toBeInTheDocument();
  });

  it("shortens a long answer at the stated length and offers the rest", async () => {
    render(<AnswerCell answer={LONG} full={false} />);

    // The cut is at a stated length, marked with an ellipsis, never silent.
    expect(screen.queryByText(LONG)).not.toBeInTheDocument();
    expect(screen.getByTestId("answer-cell")).toHaveTextContent("…");

    await userEvent.click(screen.getByTestId("answer-show-more"));

    expect(screen.getByTestId("answer-cell")).toHaveTextContent("THIS-IS-THE-END");
    expect(screen.getByTestId("answer-show-more")).toHaveTextContent("Show less");
  });

  it("leaves a short answer alone", () => {
    render(<AnswerCell answer="Paris" full={false} />);

    expect(screen.getByText("Paris")).toBeInTheDocument();
    expect(screen.queryByTestId("answer-show-more")).not.toBeInTheDocument();
  });

  it("renders an empty answer as a dash, not as a fabricated one", () => {
    render(<AnswerCell answer={null} full={false} />);

    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
