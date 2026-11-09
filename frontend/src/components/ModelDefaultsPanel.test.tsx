import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ModelDefaultsPanel } from "./ModelDefaultsPanel";
import { fetchPreferences, updatePreferences } from "../lib/preferences";
import { listProviders, type Provider } from "../lib/providers";

vi.mock("../lib/providers", () => ({ listProviders: vi.fn() }));
vi.mock("../lib/preferences", () => ({
  fetchPreferences: vi.fn(),
  updatePreferences: vi.fn(),
}));

const PROVIDERS = [
  { id: "p1", name: "Local Ollama", kind: "ollama", model_name: "llama3", is_active: true },
  { id: "p2", name: "Groq", kind: "groq", model_name: "mixtral", is_active: true },
] as unknown as Provider[];

beforeEach(() => {
  vi.mocked(listProviders).mockResolvedValue(PROVIDERS);
  vi.mocked(fetchPreferences).mockResolvedValue({ theme: "dark" });
  vi.mocked(updatePreferences).mockReset();
});

describe("ModelDefaultsPanel", () => {
  it("offers a provider for each of the three roles", async () => {
    render(<ModelDefaultsPanel />);

    await waitFor(() => {
      expect(screen.getByTestId("model-defaults-judge-provider")).toBeInTheDocument();
    });
    for (const role of ["judge", "target", "generator"]) {
      const select = screen.getByTestId(`model-defaults-${role}-provider`);
      expect(select).toHaveTextContent("Local Ollama");
      expect(select).toHaveTextContent("Groq");
    }
  });

  it("prefills the roles that are already saved to the account", async () => {
    vi.mocked(fetchPreferences).mockResolvedValue({
      theme: "light",
      judge: { provider_id: "p1", model: "llama3" },
      target: { provider_id: "p1", model: "llama3" },
      generator: { provider_id: "p2", model: "mixtral" },
    });

    render(<ModelDefaultsPanel />);

    await waitFor(() => {
      expect(vi.mocked(fetchPreferences)).toHaveBeenCalled();
    });
    expect(screen.getByTestId("model-defaults-judge-provider")).toHaveValue("p1");
    expect(screen.getByTestId("model-defaults-generator-model")).toHaveValue("mixtral");
    expect(screen.getByTestId("model-defaults-save")).toBeEnabled();
  });

  it("warns when the generator is the same provider and model as the judge", async () => {
    const user = userEvent.setup();
    vi.mocked(fetchPreferences).mockResolvedValue({
      theme: "dark",
      judge: { provider_id: "p1", model: "llama3" },
      target: { provider_id: "p1", model: "llama3" },
      generator: { provider_id: "p1", model: "llama3" },
    });

    render(<ModelDefaultsPanel />);
    await waitFor(() => {
      expect(screen.getByTestId("model-defaults-warning")).toBeInTheDocument();
    });
    // The same model writing and grading the questions needs an explicit confirmation.
    expect(screen.getByTestId("model-defaults-save")).toBeDisabled();
    await user.click(screen.getByTestId("model-defaults-confirm"));
    expect(screen.getByTestId("model-defaults-save")).toBeEnabled();
  });

  it("keeps save disabled until every role has a provider and a model", async () => {
    const user = userEvent.setup();
    render(<ModelDefaultsPanel />);
    await waitFor(() => {
      expect(screen.getByTestId("model-defaults-judge-provider")).toBeInTheDocument();
    });

    expect(screen.getByTestId("model-defaults-save")).toBeDisabled();
    await user.selectOptions(screen.getByTestId("model-defaults-judge-provider"), "p1");
    expect(screen.getByTestId("model-defaults-judge-model")).toHaveValue("llama3");
    expect(screen.getByTestId("model-defaults-save")).toBeDisabled();
  });

  it("saves the three roles and shows the confirmation", async () => {
    const user = userEvent.setup();
    vi.mocked(updatePreferences).mockResolvedValue({
      theme: "dark",
      judge: { provider_id: "p1", model: "llama3" },
      target: { provider_id: "p2", model: "mixtral" },
      generator: { provider_id: "p1", model: "phi3" },
    });

    render(<ModelDefaultsPanel />);
    await waitFor(() => {
      expect(screen.getByTestId("model-defaults-judge-provider")).toBeInTheDocument();
    });

    await user.selectOptions(screen.getByTestId("model-defaults-judge-provider"), "p1");
    await user.selectOptions(screen.getByTestId("model-defaults-target-provider"), "p2");
    await user.selectOptions(screen.getByTestId("model-defaults-generator-provider"), "p1");
    const generatorModel = screen.getByTestId("model-defaults-generator-model");
    await user.clear(generatorModel);
    await user.type(generatorModel, "phi3");
    await user.click(screen.getByTestId("model-defaults-save"));

    expect(vi.mocked(updatePreferences)).toHaveBeenCalledWith("dark", {
      judge: { provider_id: "p1", model: "llama3" },
      target: { provider_id: "p2", model: "mixtral" },
      generator: { provider_id: "p1", model: "phi3" },
    });
    await waitFor(() => {
      expect(screen.getByTestId("model-defaults-notice")).toHaveTextContent(
        "Saved to your account.",
      );
    });
  });

  it("shows the server's message when saving fails", async () => {
    const user = userEvent.setup();
    vi.mocked(updatePreferences).mockRejectedValue(new Error("Nope"));

    render(<ModelDefaultsPanel />);
    await waitFor(() => {
      expect(screen.getByTestId("model-defaults-judge-provider")).toBeInTheDocument();
    });
    await user.selectOptions(screen.getByTestId("model-defaults-judge-provider"), "p1");
    await user.selectOptions(screen.getByTestId("model-defaults-target-provider"), "p1");
    await user.selectOptions(screen.getByTestId("model-defaults-generator-provider"), "p2");
    await user.click(screen.getByTestId("model-defaults-save"));

    await waitFor(() => {
      expect(screen.getByTestId("model-defaults-error")).toBeInTheDocument();
    });
  });
});
