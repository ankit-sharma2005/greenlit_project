import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CalibrationSummary } from "./CalibrationSummary";
import { ApiError } from "../lib/api";

const { getCalibrationMock } = vi.hoisted(() => ({ getCalibrationMock: vi.fn() }));

vi.mock("../lib/labels", () => ({ getCalibration: getCalibrationMock }));

beforeEach(() => {
  vi.clearAllMocks();
});

describe("CalibrationSummary", () => {
  it("says no cases are labelled yet on a fresh project", async () => {
    getCalibrationMock.mockResolvedValue({
      labelled: 0,
      agreed: 0,
      raw_agreement: null,
      kappa: null,
      reading: "Not enough labels to read agreement yet.",
    });

    render(<CalibrationSummary />);

    expect(await screen.findByTestId("calibration-empty")).toHaveTextContent(
      "No labelled cases yet",
    );
    expect(screen.queryByTestId("calibration-kappa")).not.toBeInTheDocument();
  });

  it("shows raw agreement, kappa and the plain-language reading", async () => {
    getCalibrationMock.mockResolvedValue({
      labelled: 3,
      agreed: 2,
      raw_agreement: 0.6667,
      kappa: 0.4,
      reading:
        "Judge and reviewers agreed on 67% of labelled cases; kappa 0.40 is fair agreement " +
        "beyond chance (0 is chance, 1 is perfect).",
    });

    render(<CalibrationSummary refreshKey={2} />);

    expect(await screen.findByTestId("calibration-labelled")).toHaveTextContent("3");
    expect(screen.getByTestId("calibration-agreement")).toHaveTextContent("0.67");
    expect(screen.getByTestId("calibration-kappa")).toHaveTextContent("0.40");
    expect(screen.getByTestId("calibration-reading")).toHaveTextContent("fair agreement");
  });

  it("shows the API's message when calibration cannot be read", async () => {
    getCalibrationMock.mockRejectedValue(
      new ApiError("Your role does not allow this action.", 403, "forbidden"),
    );

    render(<CalibrationSummary />);

    expect(await screen.findByTestId("calibration-error")).toHaveTextContent(
      "Your role does not allow this action.",
    );
  });
});
