import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { JudgePanel } from "./JudgePanel";
import { ApiError } from "../lib/api";
import type { JudgeProfile } from "../lib/judgeProfiles";
import type { Provider } from "../lib/providers";

const {
  listProfilesMock,
  createProfileMock,
  selectProfileMock,
  deleteProfileMock,
  listProvidersMock,
} = vi.hoisted(() => ({
  listProfilesMock: vi.fn(),
  createProfileMock: vi.fn(),
  selectProfileMock: vi.fn(),
  deleteProfileMock: vi.fn(),
  listProvidersMock: vi.fn(),
}));

vi.mock("../lib/judgeProfiles", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/judgeProfiles")>();
  return {
    ...actual,
    listJudgeProfiles: listProfilesMock,
    createJudgeProfile: createProfileMock,
    selectJudgeProfile: selectProfileMock,
    deleteJudgeProfile: deleteProfileMock,
  };
});

vi.mock("../lib/providers", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/providers")>();
  return { ...actual, listProviders: listProvidersMock };
});

const PROVIDER = {
  id: "p1",
  name: "Ollama",
  kind: "ollama",
  model_name: "llama-3.1-8b",
  base_url: "http://host.docker.internal:11434/v1",
  is_active: true,
  timeout_seconds: 30,
  max_retries: 3,
  backoff_factor: 2,
  rate_limit_per_minute: 30,
  tokens_per_minute: null,
  is_premium: false,
  provider_config: null,
  connector: "http_endpoint",
  created_at: "2026-10-27T09:00:00Z",
  updated_at: "2026-10-27T09:00:00Z",
} as unknown as Provider;

const WARNING =
  "The judge uses the same model as the app under test (llama-3.1-8b). " +
  "A different model gives a more independent score. Saved provider: Ollama.";

function makeProfile(overrides: Partial<JudgeProfile> = {}): JudgeProfile {
  return {
    id: "j1",
    name: "The judge",
    provider_id: "p1",
    provider_name: "Ollama",
    model: "llama-3.1-8b",
    rubric_version: "1.0",
    temperature: 0,
    max_tokens: 512,
    max_cases: null,
    is_selected: true,
    created_at: "2026-10-27T09:00:00Z",
    updated_at: "2026-10-27T09:00:00Z",
    warnings: [WARNING],
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  listProvidersMock.mockResolvedValue([PROVIDER]);
  listProfilesMock.mockResolvedValue({ items: [], total: 0, selected_id: null });
});

describe("JudgePanel", () => {
  it("saves a judge from a saved provider and shows the self-grading warning", async () => {
    const user = userEvent.setup();
    createProfileMock.mockResolvedValue(makeProfile());
    // Fetched on mount (nothing saved yet) and again after saving (one profile).
    listProfilesMock
      .mockResolvedValueOnce({ items: [], total: 0, selected_id: null })
      .mockResolvedValueOnce({ items: [makeProfile()], total: 1, selected_id: "j1" });

    render(<JudgePanel />);

    // The model field follows the chosen provider, so it is prefilled and visible.
    const model = await screen.findByTestId("judge-model");
    await waitFor(() => expect(model).toHaveValue("llama-3.1-8b"));

    await user.click(screen.getByTestId("judge-save"));

    await waitFor(() => expect(createProfileMock).toHaveBeenCalledTimes(1));
    expect(createProfileMock).toHaveBeenCalledWith({
      name: "The judge",
      provider_id: "p1",
      model: "llama-3.1-8b",
      max_tokens: 512,
      // Empty cap box means "grade every case".
      max_cases: null,
    });
    expect(await screen.findByTestId("judge-notice")).toHaveTextContent("will grade your next run");
    expect(screen.getByTestId("judge-warning")).toHaveTextContent(
      "same model as the app under test",
    );
    // A refresh after saving shows the profile in the table.
    expect(await screen.findByTestId("judge-table")).toBeInTheDocument();
  });

  it("explains that a provider is needed first when none is saved", async () => {
    listProvidersMock.mockResolvedValue([]);

    render(<JudgePanel />);

    expect(await screen.findByTestId("judge-no-providers")).toHaveTextContent(
      "Add one in Settings → Providers",
    );
    expect(screen.queryByTestId("judge-save")).not.toBeInTheDocument();
  });

  it("selects a saved judge so it becomes the default", async () => {
    const user = userEvent.setup();
    const saved = makeProfile({ id: "j2", name: "Other judge", is_selected: false });
    listProfilesMock.mockResolvedValue({
      items: [makeProfile(), saved],
      total: 2,
      selected_id: "j1",
    });
    selectProfileMock.mockResolvedValue({ ...saved, is_selected: true });

    render(<JudgePanel />);

    await user.click(await screen.findByTestId("judge-select-Other judge"));

    await waitFor(() => expect(selectProfileMock).toHaveBeenCalledWith("j2"));
    expect(await screen.findByTestId("judge-notice")).toHaveTextContent(
      "will grade the answers of your next run",
    );
  });

  it("shows the API's own message when a profile cannot be saved", async () => {
    const user = userEvent.setup();
    createProfileMock.mockRejectedValue(
      new ApiError("A judge profile called 'The judge' already exists.", 409, "duplicate_name"),
    );

    render(<JudgePanel />);
    await screen.findByTestId("judge-model");
    await user.click(screen.getByTestId("judge-save"));

    expect(await screen.findByTestId("judge-error")).toHaveTextContent("already exists");
  });

  it("says plainly that runs are not judged when no judge is saved", async () => {
    render(<JudgePanel />);

    expect(await screen.findByTestId("judge-none")).toHaveTextContent(
      "Runs will not be judged until you save one",
    );
  });
});
