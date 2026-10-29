/** Upload outputs connector form: file drop, column mapping, golden dataset picker. */

import { useRef } from "react";

export interface UploadOutputsColumnOption {
  label: string;
  value: string;
}

export interface UploadOutputsDatasetOption {
  value: string;
  label: string;
}

export interface UploadOutputsPanelProps {
  file: File | null;
  fileName: string;
  detectedColumns: UploadOutputsColumnOption[];
  inputColumn: string;
  outputColumn: string;
  idColumn: string;
  contextColumn: string;
  latencyColumn: string;
  tokensInColumn: string;
  tokensOutColumn: string;
  datasetOptions: UploadOutputsDatasetOption[];
  selectedDatasetVersionId: string;
  datasetRowCount: number;
  connectorTestStatus: "idle" | "loading" | "ok" | "error";
  connectorTestMessage: string;
  disabled: boolean;
  onFileChange: (file: File | null) => void;
  onColumnChange: (
    key: "input" | "output" | "id" | "context" | "latency" | "tokens_in" | "tokens_out",
    value: string,
  ) => void;
  onDatasetChange: (versionId: string) => void;
}

const REQUIRED_COLUMNS = ["input", "output"] as const;
const OPTIONAL_COLUMNS: Array<{
  label: string;
  key: "id" | "context" | "latency" | "tokens_in" | "tokens_out";
}> = [
  { label: "id", key: "id" },
  { label: "retrieved_context", key: "context" },
  { label: "latency_ms", key: "latency" },
  { label: "tokens_in", key: "tokens_in" },
  { label: "tokens_out", key: "tokens_out" },
];

export function UploadOutputsPanel({
  file,
  fileName,
  detectedColumns,
  inputColumn,
  outputColumn,
  idColumn,
  contextColumn,
  latencyColumn,
  tokensInColumn,
  tokensOutColumn,
  datasetOptions,
  selectedDatasetVersionId,
  datasetRowCount,
  connectorTestStatus,
  connectorTestMessage,
  disabled,
  onFileChange,
  onColumnChange,
  onDatasetChange,
}: UploadOutputsPanelProps) {
  // One real file input, so the drop area, the keyboard and the e2e suite all
  // open the same chooser instead of a detached element nobody can address.
  const fileInput = useRef<HTMLInputElement | null>(null);
  const hasRequiredMapped = Boolean(inputColumn) && Boolean(outputColumn);
  const fileError =
    file && !hasRequiredMapped
      ? `File must contain the ${REQUIRED_COLUMNS.join(" and ")} columns.`
      : "";

  return (
    <div style={{ marginTop: "var(--space-5)" }}>
      {/* File drop */}
      <label className="form__label" htmlFor="upload-file">
        Upload outputs (CSV or JSON):
      </label>
      <input
        ref={fileInput}
        id="upload-file"
        data-testid="upload-file-input"
        type="file"
        accept=".csv,.json,text/csv,application/json"
        style={{ display: "none" }}
        disabled={disabled}
        onChange={(event) => {
          onFileChange(event.target.files?.[0] ?? null);
          // Reset so picking the same file again after Clear still fires.
          event.target.value = "";
        }}
      />
      <div
        style={{
          border: "var(--border)",
          borderStyle: "dashed",
          borderRadius: "var(--radius)",
          padding: "var(--space-4)",
          textAlign: "center",
          cursor: disabled ? "not-allowed" : "pointer",
          opacity: disabled ? 0.6 : 1,
        }}
        onDragOver={(e) => {
          e.preventDefault();
          e.stopPropagation();
        }}
        onDrop={(e) => {
          e.preventDefault();
          e.stopPropagation();
          if (disabled) return;
          const dropped = e.dataTransfer.files[0];
          if (
            dropped &&
            (dropped.type === "text/csv" ||
              dropped.name.endsWith(".csv") ||
              dropped.name.endsWith(".json"))
          ) {
            onFileChange(dropped);
          }
        }}
        onDragEnter={(e) => e.preventDefault()}
        onClick={() => {
          if (disabled) return;
          fileInput.current?.click();
        }}
        data-testid="upload-file-drop"
      >
        {file ? (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "var(--space-2)",
              justifyContent: "center",
            }}
          >
            <span data-testid="upload-file-name">{fileName}</span>
            <button
              type="button"
              style={{
                background: "none",
                border: "none",
                color: "var(--muted)",
                cursor: "pointer",
                padding: 0,
              }}
              onClick={(e) => {
                e.stopPropagation();
                onFileChange(null);
              }}
              data-testid="upload-file-clear"
            >
              Clear
            </button>
          </div>
        ) : (
          <span style={{ color: "var(--muted)" }}>
            Drop a CSV or JSON file here, or click to browse
          </span>
        )}
      </div>

      {/* Auto-detected columns */}
      {detectedColumns.length > 0 && (
        <div style={{ marginTop: "var(--space-4)" }}>
          <div
            style={{
              fontSize: "var(--font-size-sm)",
              color: "var(--muted)",
              marginBottom: "var(--space-2)",
            }}
          >
            {detectedColumns.length} column{detectedColumns.length === 1 ? "" : "s"} detected:
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-2)" }}>
            {detectedColumns.map((col) => (
              <span
                key={col.value}
                data-testid="upload-column-badge"
                style={{
                  background: "var(--bg-muted)",
                  borderRadius: "var(--radius)",
                  padding: "2px var(--space-2)",
                  fontSize: "var(--font-size-sm)",
                }}
              >
                {col.label}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Column mapping */}
      <div style={{ marginTop: "var(--space-4)" }}>
        <div
          style={{
            fontSize: "var(--font-size-sm)",
            color: "var(--muted)",
            marginBottom: "var(--space-2)",
          }}
        >
          Map columns in your file to the fields GreenLit expects.
          {REQUIRED_COLUMNS.join(" and ")} are required; the rest are optional.
        </div>

        {OPTIONAL_COLUMNS.map((opt) => {
          const key = opt.key;
          const current =
            key === "id"
              ? idColumn
              : key === "context"
                ? contextColumn
                : key === "latency"
                  ? latencyColumn
                  : key === "tokens_in"
                    ? tokensInColumn
                    : tokensOutColumn;
          return (
            <div key={opt.key} style={{ marginBottom: "var(--space-2)" }}>
              <label
                className="form__label"
                htmlFor={`upload-col-${key}`}
                style={{ fontSize: "var(--font-size-sm)", minWidth: "140px" }}
              >
                {opt.label} (optional):
              </label>
              <select
                id={`upload-col-${key}`}
                data-testid={`upload-col-${key}`}
                value={current}
                onChange={(e) => onColumnChange(key, e.target.value)}
                disabled={disabled || !file}
                style={{ flex: 1 }}
              >
                <option value="">None</option>
                {detectedColumns
                  .filter((c) => c.value !== current)
                  .map((col) => (
                    <option key={col.value} value={col.value}>
                      {col.label}
                    </option>
                  ))}
              </select>
            </div>
          );
        })}

        <div style={{ marginBottom: "var(--space-2)" }}>
          <label
            className="form__label"
            htmlFor="upload-col-input"
            style={{ fontSize: "var(--font-size-sm)", minWidth: "140px" }}
          >
            input (required):
          </label>
          <select
            id="upload-col-input"
            data-testid="upload-col-input"
            value={inputColumn}
            onChange={(e) => onColumnChange("input", e.target.value)}
            disabled={disabled || !file}
            style={{ flex: 1 }}
          >
            <option value="">— missing —</option>
            {detectedColumns
              .filter((c) => c.value !== inputColumn)
              .map((col) => (
                <option key={col.value} value={col.value}>
                  {col.label}
                </option>
              ))}
          </select>
        </div>

        <div style={{ marginBottom: "var(--space-2)" }}>
          <label
            className="form__label"
            htmlFor="upload-col-output"
            style={{ fontSize: "var(--font-size-sm)", minWidth: "140px" }}
          >
            output (required):
          </label>
          <select
            id="upload-col-output"
            data-testid="upload-col-output"
            value={outputColumn}
            onChange={(e) => onColumnChange("output", e.target.value)}
            disabled={disabled || !file}
            style={{ flex: 1 }}
          >
            <option value="">— missing —</option>
            {detectedColumns
              .filter((c) => c.value !== outputColumn)
              .map((col) => (
                <option key={col.value} value={col.value}>
                  {col.label}
                </option>
              ))}
          </select>
        </div>
      </div>

      {/* Connector test result */}
      {connectorTestStatus !== "idle" && (
        <div
          style={{
            marginTop: "var(--space-3)",
            padding: "var(--space-3)",
            borderRadius: "var(--radius)",
            background:
              connectorTestStatus === "error"
                ? "var(--color-error-bg)"
                : connectorTestStatus === "ok"
                  ? "var(--color-success-bg)"
                  : "var(--bg-muted)",
            color:
              connectorTestStatus === "error"
                ? "var(--color-error)"
                : connectorTestStatus === "ok"
                  ? "var(--color-success)"
                  : "var(--text)",
          }}
          data-testid="upload-connector-result"
          role={connectorTestStatus === "error" ? "alert" : "status"}
        >
          {connectorTestMessage}
        </div>
      )}

      {/* Golden dataset picker */}
      <div style={{ marginTop: "var(--space-4)" }}>
        <label className="form__label" htmlFor="upload-dataset">
          Golden dataset to score against:
        </label>
        <select
          id="upload-dataset"
          data-testid="upload-dataset"
          value={selectedDatasetVersionId}
          onChange={(e) => onDatasetChange(e.target.value)}
          disabled={disabled}
          style={{ width: "100%", marginTop: "var(--space-1)" }}
        >
          <option value="">Select an approved dataset version…</option>
          {datasetOptions.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        {selectedDatasetVersionId && (
          <p
            className="card__hint"
            style={{ marginTop: "var(--space-1)", fontSize: "var(--font-size-sm)" }}
          >
            Scoring {datasetRowCount} approved case{datasetRowCount === 1 ? "" : "s"}.
          </p>
        )}
      </div>

      {fileError && (
        <p className="form-error" role="alert" style={{ marginTop: "var(--space-3)" }}>
          {fileError}
        </p>
      )}
    </div>
  );
}
