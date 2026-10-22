import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Spinner } from "./Spinner";

describe("Spinner", () => {
  it("announces itself as a status with a default label", () => {
    render(<Spinner />);

    const status = screen.getByRole("status");
    expect(status).toHaveClass("spinner", "spinner--md");
    expect(screen.getByText("Loading")).toHaveClass("sr-only");
  });

  it("supports all sizes", () => {
    const { container, rerender } = render(<Spinner size="sm" label="Testing" />);
    expect(container.firstChild).toHaveClass("spinner--sm");

    rerender(<Spinner size="lg" label="Testing" showLabel />);
    expect(screen.getByText("Testing")).not.toHaveClass("sr-only");
  });

  it("shows the logo mark in the centre at xl size", () => {
    const { container } = render(<Spinner size="xl" label="Preparing the run" />);

    expect(container.querySelector(".spinner__mark")).toBeInTheDocument();
    expect(container.querySelector(".spinner__dot")).not.toBeInTheDocument();
    expect(screen.getByText("Preparing the run")).toBeInTheDocument();
  });

  it("uses a dot, not the logo mark, at other sizes", () => {
    const { container } = render(<Spinner size="lg" />);

    expect(container.querySelector(".spinner__dot")).toBeInTheDocument();
    expect(container.querySelector(".spinner__mark")).not.toBeInTheDocument();
  });
});
