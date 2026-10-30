import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProvidersPanel } from "./ProvidersPanel";
import type { Provider } from "../lib/providers";

const { listProvidersMock, createProviderMock, updateProviderMock } = vi.hoisted(() => ({
  listProvidersMock: vi.fn(),
  createProviderMock: vi.fn(),
  updateProviderMock: vi.fn(),
}));

vi.mock("../lib/providers", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/providers")>();
  return {
    ...actual,
    listProviders: listProvidersMock,
    createProvider: createProviderMock,
    updateProvider: updateProviderMock,
    deleteProvider: vi.fn(),
    testProvider: vi.fn(),
  };
});

function makeProvider(overrides: Partial<Provider> = {}): Provider {
  return {
    id: "provider-1",
    name: "Priced provider",
    kind: "openai-compatible",
    model_name: "gpt-4o-mini",
    base_url: "http://127.0.0.1:9999/v1",
    is_active: true,
    timeout_seconds: 30,
    max_retries: 3,
    backoff_factor: 2,
    rate_limit_per_minute: 60,
    tokens_per_minute: null,
    is_premium: false,
    provider_config: null,
    connector: "http_endpoint",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

async function fillRequiredFields(user: ReturnType<typeof userEvent.setup>) {
  await user.clear(screen.getByLabelText("Name:"));
  await user.type(screen.getByLabelText("Name:"), "My provider");
  await user.clear(screen.getByLabelText("Model:"));
  await user.type(screen.getByLabelText("Model:"), "gpt-4o-mini");
}

describe("ProvidersPanel token prices", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listProvidersMock.mockResolvedValue([]);
    createProviderMock.mockResolvedValue(makeProvider());
  });

  it("sends no price keys when both fields are left empty", async () => {
    const user = userEvent.setup();
    render(<ProvidersPanel />);

    await fillRequiredFields(user);
    await user.click(screen.getByRole("button", { name: "Add provider" }));

    await waitFor(() => expect(createProviderMock).toHaveBeenCalledTimes(1));
    // Empty means unset: no keys at all, never a 0 that reads as "free".
    expect(createProviderMock.mock.calls[0]?.[0]?.metadata).toEqual({});
  });

  it("sends both prices as numbers when they are valid", async () => {
    const user = userEvent.setup();
    render(<ProvidersPanel />);

    await fillRequiredFields(user);
    await user.type(screen.getByTestId("provider-price-in"), "0.15");
    await user.type(screen.getByTestId("provider-price-out"), "0.6");
    await user.click(screen.getByRole("button", { name: "Add provider" }));

    await waitFor(() => expect(createProviderMock).toHaveBeenCalledTimes(1));
    expect(createProviderMock.mock.calls[0]?.[0]?.metadata).toEqual({
      price_per_1k_tokens_in: 0.15,
      price_per_1k_tokens_out: 0.6,
    });
  });

  it("shows an inline error and does not submit for a non-numeric price", async () => {
    const user = userEvent.setup();
    render(<ProvidersPanel />);

    await fillRequiredFields(user);
    await user.type(screen.getByTestId("provider-price-in"), "free");
    await user.click(screen.getByRole("button", { name: "Add provider" }));

    expect(await screen.findByTestId("provider-price-error")).toHaveTextContent(
      "Enter a number, or leave this empty.",
    );
    expect(createProviderMock).not.toHaveBeenCalled();
  });

  it("shows an inline error and does not submit for a negative price", async () => {
    const user = userEvent.setup();
    render(<ProvidersPanel />);

    await fillRequiredFields(user);
    await user.type(screen.getByTestId("provider-price-out"), "-2");
    await user.click(screen.getByRole("button", { name: "Add provider" }));

    expect(await screen.findByTestId("provider-price-error")).toHaveTextContent(
      "A price cannot be negative.",
    );
    expect(createProviderMock).not.toHaveBeenCalled();
  });
});

describe("ProviderPrices editor", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    updateProviderMock.mockResolvedValue(makeProvider());
  });

  it('shows "not set" when the provider has no prices', async () => {
    listProvidersMock.mockResolvedValue([makeProvider()]);
    render(<ProvidersPanel />);

    expect(await screen.findByTestId("provider-price-summary")).toHaveTextContent("not set");
  });

  it("saves edited prices and clears the one emptied", async () => {
    const user = userEvent.setup();
    listProvidersMock.mockResolvedValue([
      makeProvider({
        provider_config: { price_per_1k_tokens_in: 0.15, price_per_1k_tokens_out: 0.6 },
      }),
    ]);
    render(<ProvidersPanel />);

    await user.click(await screen.findByTestId("provider-price-edit"));
    const outField = screen.getByTestId("provider-price-edit-out");
    await user.clear(outField);
    await user.click(screen.getByTestId("provider-price-save"));

    await waitFor(() => expect(updateProviderMock).toHaveBeenCalledTimes(1));
    // The cleared price is explicitly null, which the API turns into "remove".
    expect(updateProviderMock.mock.calls[0]?.[1]).toEqual({
      metadata: { price_per_1k_tokens_in: 0.15, price_per_1k_tokens_out: null },
    });
  });

  it("blocks an invalid edit with an inline error", async () => {
    const user = userEvent.setup();
    listProvidersMock.mockResolvedValue([makeProvider()]);
    render(<ProvidersPanel />);

    await user.click(await screen.findByTestId("provider-price-edit"));
    await user.type(screen.getByTestId("provider-price-edit-in"), "abc");
    await user.click(screen.getByTestId("provider-price-save"));

    expect(await screen.findByTestId("provider-price-error")).toBeInTheDocument();
    expect(updateProviderMock).not.toHaveBeenCalled();
  });
});
