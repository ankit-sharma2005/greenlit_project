import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ProgressBar } from "./ProgressBar";

describe("ProgressBar", () => {
  it("exposes determinate progress values", () => {
    render(<ProgressBar value={7} max={20} label="Cases done" />);

    const bar = screen.getByRole("progressbar", { name: "Cases done" });
    expect(bar).toHaveAttribute("aria-valuemin", "0");
    expect(bar).toHaveAttribute("aria-valuemax", "20");
    expect(bar).toHaveAttribute("aria-valuenow", "7");
    expect(bar).toHaveAttribute("aria-valuetext", "35%");
    expect(screen.getByText("7 / 20")).toBeInTheDocument();
  });

  it("clamps values outside the range", () => {
    render(<ProgressBar value={42} max={20} label="Cases done" />);

    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "20");
  });

  it("handles negative values without breaking the track", () => {
    render(<ProgressBar value={-3} max={10} label="Cases done" />);

    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "0");
  });

  it("can hide the numeric value", () => {
    render(<ProgressBar value={1} max={4} label="Cases done" showValue={false} />);

    expect(screen.queryByText("1 / 4")).not.toBeInTheDocument();
  });
});
