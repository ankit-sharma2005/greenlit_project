import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { WebsiteWizard, type WebsiteWizardProps } from "./WebsiteWizard";

const check: WebsiteWizardProps["check"] = {
  check_id: "check-1",
  expires_at: "2026-11-03T10:30:00Z",
  accepted: false,
  request: {
    method: "POST",
    url: "https://chat.example.com/ask",
    headers: { Authorization: "XXXX" },
    body: '{"question":"Hello"}',
    input: "Hello",
  },
  status: 200,
  latency_ms: 42,
  answer: "A short answer",
  answer_truncated: false,
  extraction_ok: true,
  mapping_path: null,
  hint: null,
  error: null,
  answer_candidates: [{ path: "choices[0].message.content", preview: "A short answer" }],
  question_path: "question",
  question_path_reason: null,
};

function renderWizard(overrides: Partial<WebsiteWizardProps> = {}) {
  const props: WebsiteWizardProps = {
    curlText: "",
    onCurlChange: vi.fn(),
    message: "",
    onMessageChange: vi.fn(),
    onRead: vi.fn(),
    canRead: true,
    busy: false,
    error: null,
    check,
    candidates: check?.answer_candidates ?? [],
    selectedPath: "",
    onSelectPath: vi.fn(),
    accepted: false,
    onAccept: vi.fn(),
    headerNames: ["Authorization"],
    onClose: vi.fn(),
    ...overrides,
  };
  render(<WebsiteWizard {...props} />);
  return props;
}

describe("WebsiteWizard", () => {
  it("shows all four plain-language steps", () => {
    renderWizard();

    expect(screen.getByText("Open the website's chatbot in your browser.")).toBeInTheDocument();
    expect(
      screen.getByText("Open DevTools → Network and send one normal message."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Right-click the request that carries your message (fetch/XHR) → Copy → Copy as cURL.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Paste it below and type the exact message you sent.")).toBeInTheDocument();
  });

  it("allows typing in the controlled cURL textarea", async () => {
    const props = renderWizard();
    const textarea = screen.getByTestId("website-curl");
    fireEvent.change(textarea, { target: { value: "curl https://chat.example.com/ask" } });

    expect(props.onCurlChange).toHaveBeenLastCalledWith("curl https://chat.example.com/ask");
  });

  it("selects an answer candidate and displays imported header values only as XXXX", async () => {
    const user = userEvent.setup();
    const props = renderWizard();
    await user.click(screen.getByTestId("website-candidate-0"));

    expect(props.onSelectPath).toHaveBeenCalledWith("choices[0].message.content");
    expect(screen.getByTestId("website-imported-headers")).toHaveTextContent(
      "Authorization: XXXX",
    );
    expect(screen.getByTestId("website-accept")).toBeDisabled();
  });

  it("runs the read action when enabled", () => {
    const props = renderWizard();
    fireEvent.click(screen.getByTestId("website-read"));

    expect(props.onRead).toHaveBeenCalledTimes(1);
  });
});
