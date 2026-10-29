import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SetupChecklist } from "./SetupChecklist";

const { testProviderMock } = vi.hoisted(() => ({ testProviderMock: vi.fn() }));

vi.mock("../lib/providers", () => ({ testProvider: testProviderMock }));

const PROVIDER = { id: "p1", name: "Ollama", modelName: "llama-3.1-8b" };

function renderChecklist(overrides: Partial<Parameters<typeof SetupChecklist>[0]> = {}) {
  return render(
    <MemoryRouter>
      <SetupChecklist providers={[]} connectorTested={false} approvedDatasets={0} {...overrides} />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("SetupChecklist", () => {
  it("names the missing step and links to it", () => {
    renderChecklist();

    expect(screen.getByTestId("setup-progress")).toHaveTextContent("0 of 3");
    expect(screen.getByTestId("setup-provider-state")).toHaveTextContent("No provider saved");
    expect(screen.getByTestId("setup-provider-link")).toHaveAttribute("href", "/settings");
    expect(screen.getByTestId("setup-dataset-link")).toHaveTextContent("Approve a dataset");
    expect(screen.queryByTestId("setup-ready")).not.toBeInTheDocument();
  });

  it("checks the provider against the provider itself", async () => {
    testProviderMock.mockResolvedValue({
      success: true,
      message: "ok",
      latency_ms: 42,
      model: "llama-3.1-8b",
      connector: "prompt_app",
    });

    renderChecklist({ providers: [PROVIDER] });
    await userEvent.click(screen.getByTestId("setup-check-provider"));

    expect(testProviderMock).toHaveBeenCalledWith("p1");
    expect(await screen.findByTestId("setup-provider-state")).toHaveTextContent("reachable");
    expect(screen.getByTestId("setup-provider-state")).toHaveTextContent("42 ms");
  });

  it("reports a provider that did not answer", async () => {
    testProviderMock.mockResolvedValue({
      success: false,
      message: "Connection error: refused",
      latency_ms: 0,
      model: null,
      connector: "prompt_app",
    });

    renderChecklist({ providers: [PROVIDER] });
    await userEvent.click(screen.getByTestId("setup-check-provider"));

    expect(await screen.findByTestId("setup-provider-state")).toHaveTextContent("did not answer");
  });

  it("says everything is ready once all three are in place", () => {
    renderChecklist({ providers: [PROVIDER], connectorTested: true, approvedDatasets: 2 });

    expect(screen.getByTestId("setup-progress")).toHaveTextContent("3 of 3");
    expect(screen.getByTestId("setup-ready")).toHaveTextContent("Everything a test needs");
    expect(screen.queryByTestId("setup-steps")).not.toBeInTheDocument();
  });

  it("points at the target field when the connector has not been tested", async () => {
    const onGoToTarget = vi.fn();
    renderChecklist({ providers: [PROVIDER], onGoToTarget });

    await userEvent.click(screen.getByTestId("setup-go-target"));

    expect(onGoToTarget).toHaveBeenCalledTimes(1);
  });
});
