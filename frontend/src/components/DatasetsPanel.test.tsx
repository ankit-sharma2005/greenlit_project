import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DatasetsPanel } from "./DatasetsPanel";

const {
  approveVersionMock,
  deleteDatasetMock,
  generateVersionMock,
  generateVersionFromSourceMock,
  listDatasetsMock,
  listItemsMock,
  listProvidersMock,
  listVersionsMock,
} = vi.hoisted(() => ({
  approveVersionMock: vi.fn(),
  deleteDatasetMock: vi.fn(),
  generateVersionMock: vi.fn(),
  generateVersionFromSourceMock: vi.fn(),
  listDatasetsMock: vi.fn(),
  listItemsMock: vi.fn(),
  listProvidersMock: vi.fn(),
  listVersionsMock: vi.fn(),
}));

vi.mock("../lib/datasets", () => ({
  approveVersion: approveVersionMock,
  deleteDataset: deleteDatasetMock,
  generateVersion: generateVersionMock,
  generateVersionFromSource: generateVersionFromSourceMock,
  listDatasets: listDatasetsMock,
  listItems: listItemsMock,
  listProviders: listProvidersMock,
  listVersions: listVersionsMock,
  uploadDataset: vi.fn(),
}));

const dataset = {
  id: "dataset-1",
  owner_id: "user-1",
  name: "Policies",
  source_filename: "seed.csv",
  file_format: "csv",
  content_hash: "a".repeat(64),
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  columns: null,
  versions: [],
};

const generatedVersion = {
  id: "version-2",
  dataset_id: dataset.id,
  version_no: 2,
  content_hash: "b".repeat(64),
  row_count: 1,
  columns_snapshot: {
    columns: ["question", "answer", "reference_context"],
    source_truncated: true,
  },
  generated: true,
  approved_by: null,
  approved_at: null,
  created_at: "2026-01-01T00:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
  listDatasetsMock.mockResolvedValue({ items: [dataset], total: 1, limit: 50, offset: 0 });
  listProvidersMock.mockResolvedValue([
    { id: "provider-1", name: "Fake provider", model_name: "fake-model", is_active: true },
  ]);
  listVersionsMock.mockResolvedValue([generatedVersion]);
  listItemsMock.mockResolvedValue({
    items: [
      {
        id: "item-1",
        dataset_version_id: "version-2",
        row_index: 0,
        data: {
          question: "What does this policy cover?",
          answer: "Tuition.",
          reference_context: "The scholarship covers tuition.",
        },
        created_at: "2026-01-01T00:00:00Z",
      },
    ],
    total: 1,
    limit: 50,
    offset: 0,
  });
  generateVersionFromSourceMock.mockResolvedValue(generatedVersion);
});

describe("DatasetsPanel source generation", () => {
  it("uploads a PDF source and previews the generated reference passage", async () => {
    const user = userEvent.setup();
    render(<DatasetsPanel />);

    await user.click(await screen.findByRole("button", { name: "Open" }));
    await user.selectOptions(await screen.findByLabelText("Provider:"), "provider-1");

    const pdf = new File(["small PDF fixture"], "policy.pdf", { type: "application/pdf" });
    await user.upload(screen.getByLabelText(/upload a source file/i), pdf);
    await user.click(screen.getByRole("button", { name: "Generate draft" }));

    expect(generateVersionFromSourceMock).toHaveBeenCalledWith(
      dataset.id,
      { provider_id: "provider-1", count: 20, source_text: undefined },
      pdf,
    );
    expect(await screen.findByRole("status")).toHaveTextContent("later text was omitted");
    expect(screen.getByText("The scholarship covers tuition.")).toBeInTheDocument();
  });
});
