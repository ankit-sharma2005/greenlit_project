import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Button, SLOW_ACTION_MS } from "./Button";

describe("Button", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("calls onClick when idle", () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Start test</Button>);

    fireEvent.click(screen.getByRole("button", { name: "Start test" }));

    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("blocks clicks, disables and shows a spinner while loading", () => {
    const onClick = vi.fn();
    render(
      <Button loading onClick={onClick}>
        Start test
      </Button>,
    );

    const button = screen.getByRole("button");
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("status")).toBeInTheDocument();

    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("keeps the label in the layout so the width does not jump", () => {
    render(<Button loading>Start test</Button>);

    expect(screen.getByText("Start test")).toHaveAttribute("data-hidden", "true");
  });

  it("announces a slow action after ten seconds", () => {
    vi.useFakeTimers();
    render(
      <Button loading loadingLabel="Starting">
        Start test
      </Button>,
    );

    expect(screen.getByRole("status")).toHaveTextContent("Starting");

    act(() => {
      vi.advanceTimersByTime(SLOW_ACTION_MS);
    });

    expect(screen.getByRole("button")).toHaveAttribute("aria-label", "Still working…");
    expect(screen.getByRole("button")).toHaveAttribute("data-slow", "true");
  });

  it("resets when loading ends", () => {
    const { rerender } = render(<Button loading>Start test</Button>);
    expect(screen.getByRole("button")).toBeDisabled();

    rerender(<Button>Start test</Button>);

    expect(screen.getByRole("button")).toBeEnabled();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
