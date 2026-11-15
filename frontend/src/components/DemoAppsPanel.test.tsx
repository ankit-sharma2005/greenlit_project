import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DemoAppsPanel } from "./DemoAppsPanel";

const mocks = vi.hoisted(() => ({
  listDemoApps: vi.fn(),
  connectDemoApp: vi.fn(),
}));

vi.mock("../lib/demoApps", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/demoApps")>();
  return {
    ...actual,
    listDemoApps: mocks.listDemoApps,
    connectDemoApp: mocks.connectDemoApp,
  };
});

const WARNING =
  "This is a local demo app: it has no authentication and is weak by design. " +
  "It is reachable only from this computer and must never be exposed to the internet.";

const APPS = [
  {
    id: "math-solver",
    name: "Acme math solver",
    description: "Deterministic arithmetic.",
    entry_point: "http_endpoint",
    url: "http://host.docker.internal:9115/",
    method: "POST",
    response_format: "json",
    answer_path: "$.answer",
    context_path: null,
    body_template: '{"question": "{{question}}"}',
    timeout_seconds: 30,
    mcp_tool: null,
    start_bash: "cd experiments/llm_apps && python math_solver/app.py",
    start_windows: "cd experiments\\llm_apps; python math_solver\\app.py",
    modes: [{ mode: "correct", shows: "every answer is right" }],
    status: { state: "up" as const, app: "math-solver", mode: "correct", provider: "none", model: "none" },
  },
  {
    id: "support-bot",
    name: "Acme support bot",
    description: "A support persona.",
    entry_point: "http_endpoint",
    url: "http://host.docker.internal:9111/",
    method: "POST",
    response_format: "json",
    answer_path: "$.answer",
    context_path: null,
    body_template: '{"question": "{{question}}"}',
    timeout_seconds: 150,
    mcp_tool: null,
    start_bash: "cd experiments/llm_apps && python support_bot/app.py",
    start_windows: "cd experiments\\llm_apps; python support_bot\\app.py",
    modes: [{ mode: "guarded", shows: "the reviewed prompt" }],
    status: { state: "down" as const },
  },
];

function renderPanel() {
  return render(
    <MemoryRouter>
      <DemoAppsPanel />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.listDemoApps.mockResolvedValue({ items: APPS, warning: WARNING });
  mocks.connectDemoApp.mockResolvedValue({
    target: { id: "target-1" },
    created: true,
    warning: WARNING,
  });
});

describe("Demo apps panel", () => {
  it("shows a card per app with its up and down states", async () => {
    renderPanel();

    await waitFor(() => expect(screen.getByTestId("demo-card-math-solver")).toBeInTheDocument());
    expect(screen.getAllByTestId(/^demo-card-/)).toHaveLength(2);
    expect(screen.getByTestId("demo-status-math-solver")).toHaveTextContent("running");
    expect(screen.getByTestId("demo-mode-math-solver")).toHaveTextContent("Mode: correct");
    expect(screen.getByTestId("demo-status-support-bot")).toHaveTextContent("not running");
    expect(screen.getByTestId("demo-mode-support-bot")).toHaveTextContent("not reported");
    expect(screen.getByTestId("demo-apps-warning")).toHaveTextContent("never be exposed");
  });

  it("copies the start command for the chosen platform", async () => {
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, "writeText");
    renderPanel();

    await waitFor(() => expect(screen.getByTestId("demo-card-math-solver")).toBeInTheDocument());
    await user.click(screen.getByTestId("demo-copy-math-solver"));
    expect(writeText).toHaveBeenCalledWith(APPS[0]!.start_windows);

    await user.click(screen.getByTestId("demo-platform-bash"));
    await user.click(screen.getByTestId("demo-copy-math-solver"));
    expect(writeText).toHaveBeenLastCalledWith(APPS[0]!.start_bash);
  });

  it("confirms with the local-only warning before connecting, then offers a smoke test", async () => {
    const user = userEvent.setup();
    renderPanel();

    await waitFor(() => expect(screen.getByTestId("demo-card-math-solver")).toBeInTheDocument());
    expect(mocks.connectDemoApp).not.toHaveBeenCalled();

    await user.click(screen.getByTestId("demo-connect-math-solver"));
    expect(screen.getByTestId("demo-confirm-math-solver")).toHaveTextContent(
      "never expose it to the internet",
    );

    await user.click(screen.getByTestId("demo-confirm-yes-math-solver"));
    await waitFor(() => expect(mocks.connectDemoApp).toHaveBeenCalledWith("math-solver"));
    await waitFor(() => expect(screen.getByTestId("demo-smoke-math-solver")).toBeInTheDocument());
    expect(screen.getByTestId("demo-smoke-math-solver")).toHaveAttribute(
      "href",
      "/?demo_app=math-solver",
    );
    expect(screen.getByTestId("demo-open-math-solver")).toBeInTheDocument();
  });

  it("says so when the catalog cannot be loaded", async () => {
    mocks.listDemoApps.mockRejectedValue(new Error("offline"));
    renderPanel();
    await waitFor(() => expect(screen.getByTestId("demo-apps-error")).toBeInTheDocument());
  });
});
