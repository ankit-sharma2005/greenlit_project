import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { UploadOutputsPanel } from "../UploadOutputsPanel";

function renderPanel(
  overrides: Partial<React.ComponentProps<typeof UploadOutputsPanel>> = {},
) {
  const props = {
    file: null,
    fileName: "",
    detectedColumns: [],
    inputColumn: "",
    outputColumn: "",
    idColumn: "",
    contextColumn: "",
    latencyColumn: "",
    tokensInColumn: "",
    tokensOutColumn: "",
    datasetOptions: [],
    selectedDatasetVersionId: "",
    datasetRowCount: 0,
    connectorTestStatus: "idle" as const,
    connectorTestMessage: "",
    disabled: false,
    onFileChange: vi.fn(),
    onColumnChange: vi.fn(),
    onDatasetChange: vi.fn(),
    ...overrides,
  };
  return { ...render(<UploadOutputsPanel {...props} />), props };
}

describe("UploadOutputsPanel", () => {
  it("shows a file drop area with browse prompt when no file is loaded", () => {
    renderPanel();

    expect(screen.getByTestId("upload-file-drop")).toBeInTheDocument();
    expect(screen.getByText(/drop a csv or json file here/i)).toBeInTheDocument();
  });

  it("shows the file name and a clear button after a file is loaded", () => {
    const onFileChange = vi.fn();
    renderPanel({
      file: new File(["hello"], "outputs.csv", { type: "text/csv" }),
      fileName: "outputs.csv",
      onFileChange,
    });

    expect(screen.getByTestId("upload-file-name")).toHaveTextContent("outputs.csv");
    expect(screen.getByTestId("upload-file-clear")).toBeInTheDocument();
  });

  it("clears the file when the clear button is clicked", async () => {
    const user = userEvent.setup();
    const onFileChange = vi.fn();
    renderPanel({
      file: new File(["hello"], "outputs.csv", { type: "text/csv" }),
      fileName: "outputs.csv",
      onFileChange,
    });

    await user.click(screen.getByTestId("upload-file-clear"));
    expect(onFileChange).toHaveBeenCalledWith(null);
  });

  it("shows detected columns after a file is loaded", () => {
    const { container } = renderPanel({
      file: new File(["hello"], "outputs.csv", { type: "text/csv" }),
      fileName: "outputs.csv",
      detectedColumns: [
        { label: "question", value: "question" },
        { label: "answer", value: "answer" },
      ],
    });

    expect(screen.getByText(/2 columns detected/i)).toBeInTheDocument();
    const badges = container.querySelectorAll(
      "[data-testid=\"upload-column-badge\"]",
    );
    expect(badges).toHaveLength(2);
    expect(badges[0]).toHaveTextContent("question");
    expect(badges[1]).toHaveTextContent("answer");
  });

  it("does not show an error when both required columns are mapped", () => {
    renderPanel({
      file: new File(["hello"], "good.csv", { type: "text/csv" }),
      fileName: "good.csv",
      detectedColumns: [
        { label: "question", value: "question" },
        { label: "answer", value: "answer" },
      ],
      inputColumn: "question",
      outputColumn: "answer",
    });

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows an error message when the file is missing required columns", () => {
    renderPanel({
      file: new File(["hello"], "bad.csv", { type: "text/csv" }),
      fileName: "bad.csv",
      detectedColumns: [{ label: "foo", value: "foo" }],
    });

    expect(
      screen.getByText(/file must contain the input and output columns/i),
    ).toBeInTheDocument();
  });

  it("renders a mapping select for each optional column", () => {
    renderPanel({
      file: new File(["hello"], "outputs.csv", { type: "text/csv" }),
      fileName: "outputs.csv",
      detectedColumns: [
        { label: "id", value: "id" },
        { label: "question", value: "question" },
        { label: "answer", value: "answer" },
        { label: "context", value: "context" },
        { label: "latency_ms", value: "latency_ms" },
        { label: "tokens_in", value: "tokens_in" },
        { label: "tokens_out", value: "tokens_out" },
      ],
    });

    expect(screen.getByLabelText(/id \(optional\)/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/retrieved_context \(optional\)/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/latency_ms \(optional\)/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/tokens_in \(optional\)/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/tokens_out \(optional\)/i)).toBeInTheDocument();
  });

  it("calls onColumnChange with the right key when an optional column is picked", async () => {
    const user = userEvent.setup();
    const onColumnChange = vi.fn();
    renderPanel({
      file: new File(["hello"], "outputs.csv", { type: "text/csv" }),
      fileName: "outputs.csv",
      detectedColumns: [
        { label: "id", value: "id" },
        { label: "question", value: "question" },
        { label: "answer", value: "answer" },
        { label: "context", value: "context" },
        { label: "latency_ms", value: "latency_ms" },
        { label: "tokens_in", value: "tokens_in" },
        { label: "tokens_out", value: "tokens_out" },
      ],
      onColumnChange,
    });

    await user.selectOptions(screen.getByLabelText(/context \(optional\)/i), "context");
    expect(onColumnChange).toHaveBeenCalledWith("context", "context");
  });

  it("shows the optional column dropdowns disabled when no file is loaded", () => {
    renderPanel();

    expect(screen.getByLabelText(/id \(optional\)/i)).toBeDisabled();
    expect(screen.getByLabelText(/retrieved_context \(optional\)/i)).toBeDisabled();
    expect(screen.getByLabelText(/latency_ms \(optional\)/i)).toBeDisabled();
    expect(screen.getByLabelText(/tokens_in \(optional\)/i)).toBeDisabled();
    expect(screen.getByLabelText(/tokens_out \(optional\)/i)).toBeDisabled();
  });

  it("shows the required input and output column selectors", () => {
    renderPanel({
      file: new File(["hello"], "outputs.csv", { type: "text/csv" }),
      fileName: "outputs.csv",
      detectedColumns: [
        { label: "question", value: "question" },
        { label: "answer", value: "answer" },
      ],
    });

    expect(screen.getByLabelText(/input \(required\)/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/output \(required\)/i)).toBeInTheDocument();
  });

  it("defaults the input and output selects to missing when no column is mapped", () => {
    renderPanel({
      file: new File(["hello"], "outputs.csv", { type: "text/csv" }),
      fileName: "outputs.csv",
      detectedColumns: [
        { label: "question", value: "question" },
        { label: "answer", value: "answer" },
      ],
      inputColumn: "",
      outputColumn: "",
    });

    expect(screen.getByLabelText(/input \(required\)/i)).toHaveValue("");
    expect(screen.getByLabelText(/output \(required\)/i)).toHaveValue("");
  });

  it("calls onColumnChange when the required input column is picked", async () => {
    const user = userEvent.setup();
    const onColumnChange = vi.fn();
    renderPanel({
      file: new File(["hello"], "outputs.csv", { type: "text/csv" }),
      fileName: "outputs.csv",
      detectedColumns: [
        { label: "question", value: "question" },
        { label: "answer", value: "answer" },
      ],
      onColumnChange,
    });

    await user.selectOptions(screen.getByLabelText(/input \(required\)/i), "question");
    expect(onColumnChange).toHaveBeenCalledWith("input", "question");
  });

  it("shows the connector test result when status is not idle", () => {
    renderPanel({
      connectorTestStatus: "ok",
      connectorTestMessage: "Connection test successful",
    });

    expect(screen.getByTestId("upload-connector-result")).toBeInTheDocument();
    expect(screen.getByText("Connection test successful")).toBeInTheDocument();
  });

  it("renders the connector error in red", () => {
    renderPanel({
      connectorTestStatus: "error",
      connectorTestMessage: "Could not find an input column",
    });

    const result = screen.getByTestId("upload-connector-result");
    expect(result).toHaveAttribute("role", "alert");
    expect(result).toHaveTextContent("Could not find an input column");
  });

  it("shows the dataset picker with approved versions", () => {
    renderPanel({
      datasetOptions: [
        { value: "v1", label: "Helpdesk cases · v1 (12 cases)" },
        { value: "v2", label: "Support queries · v2 (5 cases)" },
      ],
    });

    const select = screen.getByTestId("upload-dataset") as HTMLSelectElement;
    expect(select).toHaveValue("");
    expect(select.options[1]).toHaveTextContent(/helpdesk cases · v1/i);
    expect(select.options[2]).toHaveTextContent(/support queries · v2/i);
  });

  it("shows the row count when a dataset version is selected", () => {
    renderPanel({
      datasetOptions: [
        { value: "v1", label: "Helpdesk cases · v1 (12 cases)" },
      ],
      selectedDatasetVersionId: "v1",
      datasetRowCount: 12,
    });

    expect(screen.getByText(/scoring 12 approved cases/i)).toBeInTheDocument();
  });

  it("shows the dataset picker disabled when the panel is disabled", () => {
    renderPanel({ disabled: true });

    expect(screen.getByTestId("upload-dataset")).toBeDisabled();
  });

  it("calls onDatasetChange when a dataset version is selected", async () => {
    const user = userEvent.setup();
    const onDatasetChange = vi.fn();
    renderPanel({
      datasetOptions: [
        { value: "v1", label: "Helpdesk cases · v1 (12 cases)" },
      ],
      onDatasetChange,
    });

    await user.selectOptions(screen.getByTestId("upload-dataset"), "v1");
    expect(onDatasetChange).toHaveBeenCalledWith("v1");
  });

  it("does not render the connector result when status is idle", () => {
    renderPanel({ connectorTestStatus: "idle" });

    expect(screen.queryByTestId("upload-connector-result")).not.toBeInTheDocument();
  });
});
