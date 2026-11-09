import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DatasetDrafting } from "./DatasetDrafting";
import { DraftReview } from "./DraftReview";
import {
  approveAllDraftItems,
  createDraft,
  getDraft,
  publishDraft,
  reviewDraftItem,
  type DatasetDraft,
} from "../lib/drafts";
import { fetchPreferences } from "../lib/preferences";
import { listProviders, type Provider } from "../lib/providers";

vi.mock("../lib/drafts", () => ({
  approveAllDraftItems: vi.fn(),
  createDraft: vi.fn(),
  getDraft: vi.fn(),
  publishDraft: vi.fn(),
  reviewDraftItem: vi.fn(),
}));
vi.mock("../lib/providers", () => ({ listProviders: vi.fn() }));
vi.mock("../lib/preferences", () => ({ fetchPreferences: vi.fn() }));

const PROVIDERS = [
  { id: "p1", name: "Local Ollama", kind: "ollama", model_name: "llama3", is_active: true },
] as unknown as Provider[];

function makeDraft(overrides: Partial<DatasetDraft> = {}): DatasetDraft {
  return {
    id: "d1",
    name: "Shop questions",
    app_description: "A shop assistant.",
    requested_count: 2,
    kinds: ["document_fact"],
    generator_provider_id: "p1",
    generator_provider_name: "Local Ollama",
    generated_by_model: "llama3",
    prompt_version: "draft-v1",
    same_as_judge: false,
    status: "draft",
    published_dataset_id: null,
    published_version_id: null,
    created_at: "2026-11-09T10:00:00Z",
    items: [
      {
        id: "i1",
        row_index: 0,
        question: "What is the refund window?",
        expected_answer: "Thirty days.",
        source_passage: "Refunds within thirty days.",
        kind: "document_fact",
        status: "pending",
        edited: false,
        generated_by_model: "llama3",
        generator_provider: "Local Ollama",
        prompt_version: "draft-v1",
        reviewed_at: null,
      },
      {
        id: "i2",
        row_index: 1,
        question: "Can I cancel an order?",
        expected_answer: "Yes, before shipping.",
        source_passage: null,
        kind: "document_fact",
        status: "pending",
        edited: false,
        generated_by_model: "llama3",
        generator_provider: "Local Ollama",
        prompt_version: "draft-v1",
        reviewed_at: null,
      },
    ],
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(listProviders).mockResolvedValue(PROVIDERS);
  vi.mocked(fetchPreferences).mockResolvedValue({ theme: "dark" });
  vi.mocked(createDraft).mockReset();
  vi.mocked(reviewDraftItem).mockReset();
  vi.mocked(approveAllDraftItems).mockReset();
  vi.mocked(publishDraft).mockReset();
  vi.mocked(getDraft).mockReset();
});

describe("draft generation", () => {
  it("keeps Generate disabled until the form is complete", async () => {
    const user = userEvent.setup();
    render(<DatasetDrafting />);

    await waitFor(() => {
      expect(screen.getByTestId("draft-provider")).toHaveTextContent("Local Ollama");
    });
    expect(screen.getByTestId("draft-generate")).toBeDisabled();

    await user.type(screen.getByTestId("draft-name"), "Shop questions");
    await user.type(screen.getByTestId("draft-description"), "A shop assistant.");
    await user.selectOptions(screen.getByTestId("draft-provider"), "p1");
    expect(screen.getByTestId("draft-model")).toHaveValue("llama3");
    expect(screen.getByTestId("draft-generate")).toBeEnabled();
  });

  it("warns and needs a confirmation when the generator is the judge", async () => {
    vi.mocked(fetchPreferences).mockResolvedValue({
      theme: "dark",
      judge: { provider_id: "p1", model: "llama3" },
    });
    const user = userEvent.setup();
    render(<DatasetDrafting />);

    await waitFor(() => {
      expect(screen.getByTestId("draft-provider")).toHaveTextContent("Local Ollama");
    });
    await user.type(screen.getByTestId("draft-name"), "Shop questions");
    await user.type(screen.getByTestId("draft-description"), "A shop assistant.");
    await user.selectOptions(screen.getByTestId("draft-provider"), "p1");

    expect(screen.getByTestId("draft-generator-warning")).toBeInTheDocument();
    expect(screen.getByTestId("draft-generate")).toBeDisabled();
    await user.click(screen.getByTestId("draft-generator-confirm"));
    expect(screen.getByTestId("draft-generate")).toBeEnabled();
  });

  it("shows the generated draft in the review table", async () => {
    vi.mocked(createDraft).mockResolvedValue(makeDraft());
    const user = userEvent.setup();
    render(<DatasetDrafting />);

    await waitFor(() => {
      expect(screen.getByTestId("draft-provider")).toHaveTextContent("Local Ollama");
    });
    await user.type(screen.getByTestId("draft-name"), "Shop questions");
    await user.type(screen.getByTestId("draft-description"), "A shop assistant.");
    await user.selectOptions(screen.getByTestId("draft-provider"), "p1");
    await user.click(screen.getByTestId("draft-generate"));

    await waitFor(() => {
      expect(screen.getByTestId("draft-review")).toBeInTheDocument();
    });
    expect(screen.getByTestId("draft-count-pending")).toHaveTextContent("2 pending");
    expect(screen.getByTestId("draft-items")).toHaveTextContent("What is the refund window?");
    expect(vi.mocked(createDraft)).toHaveBeenCalledWith(
      expect.objectContaining({ name: "Shop questions", provider_id: "p1", model: "llama3" }),
    );
  });
});

describe("draft review", () => {
  it("approves an item and enables publishing only when something is approved", async () => {
    const approved = makeDraft({
      items: makeDraft().items.map((item, index) =>
        index === 0 ? { ...item, status: "approved" } : item,
      ),
    });
    vi.mocked(reviewDraftItem).mockResolvedValue(approved);
    const onChange = vi.fn();
    const user = userEvent.setup();

    const { rerender } = render(<DraftReview draft={makeDraft()} onChange={onChange} />);
    expect(screen.getByTestId("draft-publish")).toBeDisabled();

    await user.click(screen.getByTestId("draft-item-approve-i1"));
    expect(vi.mocked(reviewDraftItem)).toHaveBeenCalledWith("d1", "i1", { status: "approved" });
    expect(onChange).toHaveBeenCalledWith(approved);

    rerender(<DraftReview draft={approved} onChange={onChange} />);
    expect(screen.getByTestId("draft-count-approved")).toHaveTextContent("1 approved");
    expect(screen.getByTestId("draft-publish")).toBeEnabled();
  });

  it("rejects an item and edits one through the same endpoint", async () => {
    const rejected = makeDraft();
    rejected.items[1] = { ...rejected.items[1]!, status: "rejected" };
    vi.mocked(reviewDraftItem).mockResolvedValue(rejected);
    const user = userEvent.setup();

    render(<DraftReview draft={makeDraft()} onChange={vi.fn()} />);
    await user.click(screen.getByTestId("draft-item-reject-i2"));
    expect(vi.mocked(reviewDraftItem)).toHaveBeenCalledWith("d1", "i2", { status: "rejected" });

    await user.click(screen.getByTestId("draft-item-edit-i2"));
    const question = screen.getByTestId("draft-item-question-i2");
    await user.clear(question);
    await user.type(question, "Edited question");
    await user.click(screen.getByTestId("draft-item-save-i2"));
    expect(vi.mocked(reviewDraftItem)).toHaveBeenCalledWith("d1", "i2", {
      question: "Edited question",
      expected_answer: "Yes, before shipping.",
      source_passage: "",
    });
  });

  it("approves every pending item after a confirmation", async () => {
    const confirmed = vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(approveAllDraftItems).mockResolvedValue(makeDraft());
    const user = userEvent.setup();

    render(<DraftReview draft={makeDraft()} onChange={vi.fn()} />);
    await user.click(screen.getByTestId("draft-approve-all"));

    expect(confirmed).toHaveBeenCalled();
    expect(vi.mocked(approveAllDraftItems)).toHaveBeenCalledWith("d1");
    confirmed.mockRestore();
  });

  it("publishes approved items and names the model in the notice", async () => {
    const approved = makeDraft({
      items: makeDraft().items.map((item) => ({ ...item, status: "approved" as const })),
    });
    vi.mocked(publishDraft).mockResolvedValue({
      id: "v1",
      dataset_id: "ds1",
      version_no: 1,
      content_hash: "abc",
      row_count: 2,
      columns_snapshot: null,
      generated: true,
      approved_by: "u1",
      approved_at: "2026-11-09T10:05:00Z",
      created_at: "2026-11-09T10:05:00Z",
    });
    vi.mocked(getDraft).mockResolvedValue({ ...approved, status: "published", published_version_id: "v1" });
    const user = userEvent.setup();

    render(<DraftReview draft={approved} onChange={vi.fn()} />);
    await user.click(screen.getByTestId("draft-publish"));

    await waitFor(() => {
      expect(screen.getByTestId("draft-review-notice")).toHaveTextContent(
        "only approved items are included",
      );
    });
    expect(screen.getByTestId("draft-review-notice")).toHaveTextContent("Generated by llama3");
  });
});
