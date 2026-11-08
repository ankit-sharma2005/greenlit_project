import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { VerdictGauge } from "./VerdictGauge";

const THRESHOLDS = { review: 0.6, go: 0.8 };

describe("VerdictGauge", () => {
  it("draws three bands with the verdict word and the score marker beside the bar", () => {
    render(<VerdictGauge score={0.92} verdict="GO" thresholds={THRESHOLDS} />);

    const svg = screen.getByTestId("verdict-gauge-svg");
    expect(svg).toHaveAttribute("role", "img");
    expect(svg).toHaveAttribute(
      "aria-label",
      "Weighted score 0.92, verdict Go. NO-GO below 0.60, REVIEW from 0.60 to 0.80, " +
        "GO at or above 0.80.",
    );
    expect(svg).toHaveTextContent("Go · 0.92");
    expect(screen.getByTestId("verdict-gauge-band-NO_GO")).toBeInTheDocument();
    expect(screen.getByTestId("verdict-gauge-band-REVIEW")).toBeInTheDocument();
    expect(screen.getByTestId("verdict-gauge-band-GO")).toBeInTheDocument();
    // The verdict word is text, not colour: NO-GO, REVIEW and GO each appear as words.
    expect(svg).toHaveTextContent("NO-GO");
    expect(svg).toHaveTextContent("REVIEW");
    expect(svg).toHaveTextContent("GO");
    // The score sits inside the GO band, next to its word.
    expect(screen.getByTestId("verdict-gauge-marker")).toBeInTheDocument();
  });

  it("puts the marker on the GO side for a high score and on the REVIEW side for 0.70", () => {
    const { rerender } = render(<VerdictGauge score={0.7} verdict="REVIEW" thresholds={THRESHOLDS} />);
    const svg = screen.getByTestId("verdict-gauge-svg");
    const marker = screen.getByTestId("verdict-gauge-marker");
    expect(marker).toHaveAttribute("points", expect.stringContaining("234.8"));
    rerender(<VerdictGauge score={0.92} verdict="GO" thresholds={THRESHOLDS} />);
    expect(svg).toHaveTextContent("Go · 0.92");
  });

  it("exposes the same numbers in a toggleable data table", async () => {
    const user = userEvent.setup();
    render(<VerdictGauge score={0.92} verdict="GO" thresholds={THRESHOLDS} />);

    const toggle = screen.getByText("Show data table");
    await user.click(toggle);

    const table = screen.getByTestId("verdict-gauge-table");
    expect(table).toHaveTextContent("No-Go");
    expect(table).toHaveTextContent("Review");
    expect(table).toHaveTextContent("Go");
    expect(table).toHaveTextContent("0.00 to 0.60");
    expect(table).toHaveTextContent("0.60 to 0.80");
    expect(table).toHaveTextContent("0.80 to 1.00");
    expect(table).toHaveTextContent("0.92");
    expect(table).toHaveTextContent("Go");
  });
});
