import { useCallback, useEffect, useState } from "react";

import { ApiError } from "../lib/api";
import {
  approveVersion,
  deleteDataset,
  generateVersion,
  generateVersionFromSource,
  listDatasets,
  listItems,
  listProviders,
  listVersions,
  uploadDataset,
  type Dataset,
  type DatasetItem,
  type DatasetVersion,
  type ProviderSummary,
} from "../lib/datasets";
import { Button } from "./Button";
import { Spinner } from "./Spinner";
import "../styles/datasets.css";

function shortHash(hash: string): string {
  return hash.slice(0, 8);
}

function mappingValue(value: string | null): string {
  return value ?? "—";
}

/** The Datasets tab: upload, inspect columns, generate with preview, approve, delete. */
export function DatasetsPanel() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [providers, setProviders] = useState<ProviderSummary[]>([]);
  const [selected, setSelected] = useState<Dataset | null>(null);
  const [versions, setVersions] = useState<DatasetVersion[]>([]);

  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);

  const [generateProviderId, setGenerateProviderId] = useState("");
  const [generateCount, setGenerateCount] = useState(20);
  const [sourceText, setSourceText] = useState("");
  const [sourceFile, setSourceFile] = useState<File | null>(null);

  const [preview, setPreview] = useState<{ versionNo: number; items: DatasetItem[] } | null>(null);

  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const showError = (caught: unknown) => {
    if (caught instanceof ApiError) {
      setError(caught.message);
    } else {
      setError("Something went wrong. Try again.");
    }
  };

  const refresh = useCallback(async () => {
    try {
      const response = await listDatasets();
      setDatasets(response.items);
    } catch (caught) {
      showError(caught);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    listProviders()
      .then((items) => {
        setProviders(items.filter((provider) => provider.is_active));
      })
      .catch(() => setProviders([]));
  }, [refresh]);

  const openDataset = async (dataset: Dataset) => {
    setError(null);
    setNotice(null);
    setPreview(null);
    setSelected(dataset);
    try {
      setVersions(await listVersions(dataset.id));
    } catch (caught) {
      showError(caught);
    }
  };

  const handleUpload = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setNotice(null);
    if (!name.trim() || !file) {
      setError("Give the dataset a name and pick a file (csv, json, jsonl or xlsx).");
      return;
    }
    setBusy(true);
    try {
      const dataset = await uploadDataset(name.trim(), file);
      setName("");
      setFile(null);
      setNotice(
        `Uploaded “${dataset.name}” — version 1 with its column mapping is ready. ` +
          "Review the mapping below, then generate more cases or approve it.",
      );
      await refresh();
      await openDataset(dataset);
    } catch (caught) {
      showError(caught);
    } finally {
      setBusy(false);
    }
  };

  const handleGenerate = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!selected) {
      return;
    }
    setError(null);
    setNotice(null);
    if (sourceFile && sourceFile.size > 5 * 1024 * 1024) {
      setError("Source files must be 5 MB or smaller.");
      return;
    }
    setBusy(true);
    try {
      const request = {
        provider_id: generateProviderId,
        count: generateCount,
        source_text: sourceText.trim() ? sourceText.trim() : undefined,
      };
      const version = sourceFile
        ? await generateVersionFromSource(selected.id, request, sourceFile)
        : await generateVersion(selected.id, request);
      setNotice(
        `Draft version ${version.version_no} generated with ${version.row_count} cases. ` +
          "Review the preview, then approve it to make it usable in runs." +
          (version.columns_snapshot?.source_truncated === true
            ? " The source was longer than the passage limit, so later text was omitted."
            : ""),
      );
      setVersions(await listVersions(selected.id));
      const items = await listItems(selected.id, version.version_no);
      setPreview({ versionNo: version.version_no, items: items.items });
    } catch (caught) {
      showError(caught);
    } finally {
      setBusy(false);
    }
  };

  const handlePreview = async (versionNo: number) => {
    if (!selected) {
      return;
    }
    setError(null);
    try {
      const items = await listItems(selected.id, versionNo);
      setPreview({ versionNo, items: items.items });
    } catch (caught) {
      showError(caught);
    }
  };

  const handleApprove = async (versionNo: number) => {
    if (!selected) {
      return;
    }
    setError(null);
    try {
      await approveVersion(selected.id, versionNo);
      setNotice(`Version ${versionNo} is approved and can be used in runs.`);
      setVersions(await listVersions(selected.id));
    } catch (caught) {
      showError(caught);
    }
  };

  const handleDelete = async (dataset: Dataset) => {
    if (!window.confirm(`Delete “${dataset.name}” and all of its versions?`)) {
      return;
    }
    setError(null);
    try {
      await deleteDataset(dataset.id);
      setNotice(`Deleted “${dataset.name}”.`);
      if (selected?.id === dataset.id) {
        setSelected(null);
        setVersions([]);
        setPreview(null);
      }
      await refresh();
    } catch (caught) {
      showError(caught);
    }
  };

  return (
    <div>
      <section className="card" aria-labelledby="datasets-upload">
        <div className="card__header">
          <h3 id="datasets-upload">Upload a dataset</h3>
          <p className="card__hint">
            CSV, JSON, JSONL or XLSX. The input and output columns are detected automatically —
            correct them afterwards if needed. Files stay private to your account.
          </p>
        </div>
        <form onSubmit={handleUpload} className="datasets__upload">
          <label className="form__label" htmlFor="dataset-name">
            Dataset name:
          </label>
          <input
            id="dataset-name"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Golden questions"
            disabled={busy}
          />
          <label className="form__label" htmlFor="dataset-file">
            File:
          </label>
          <input
            id="dataset-file"
            type="file"
            accept=".csv,.json,.jsonl,.xlsx"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            disabled={busy}
          />
          <div className="datasets__actions" style={{ marginTop: "var(--space-3)" }}>
            <Button type="submit" variant="primary" loading={busy}>
              {busy ? <Spinner size="sm" label="Uploading" /> : "Upload"}
            </Button>
          </div>
        </form>
      </section>

      {error && (
        <p className="form-error" role="alert" style={{ marginTop: "var(--space-4)" }}>
          {error}
        </p>
      )}
      {notice && (
        <div
          className="notice"
          role="status"
          data-testid="datasets-notice"
          style={{ marginTop: "var(--space-4)" }}
        >
          {notice}
        </div>
      )}

      <section
        className="card"
        aria-labelledby="datasets-list"
        style={{ marginTop: "var(--space-5)" }}
      >
        <div className="card__header">
          <h3 id="datasets-list">Your datasets</h3>
        </div>
        {loading ? (
          <Spinner size="md" label="Loading datasets" showLabel />
        ) : datasets.length === 0 ? (
          <p className="card__hint">
            Nothing here yet — upload your first dataset above. You can also generate one with the
            LLM once a provider is configured in Providers and models.
          </p>
        ) : (
          <table className="datasets__table" data-testid="datasets-table">
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Format</th>
                <th scope="col">Filename</th>
                <th scope="col">Hash</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {datasets.map((dataset) => (
                <tr
                  key={dataset.id}
                  className={selected?.id === dataset.id ? "datasets__row--selected" : undefined}
                >
                  <td>{dataset.name}</td>
                  <td>{dataset.file_format}</td>
                  <td>{dataset.source_filename}</td>
                  <td>
                    <code title={dataset.content_hash}>{shortHash(dataset.content_hash)}</code>
                  </td>
                  <td>
                    <div className="datasets__actions">
                      <Button
                        variant="secondary"
                        onClick={() => void openDataset(dataset)}
                        data-testid="open-dataset"
                      >
                        Open
                      </Button>
                      <Button variant="secondary" onClick={() => void handleDelete(dataset)}>
                        Delete
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {selected && (
        <section
          className="card"
          aria-labelledby="datasets-detail"
          style={{ marginTop: "var(--space-5)" }}
        >
          <div className="card__header">
            <h3 id="datasets-detail">{selected.name}</h3>
            <p className="card__hint">
              {selected.source_filename} · {selected.file_format} · hash{" "}
              <code title={selected.content_hash}>{shortHash(selected.content_hash)}</code>
            </p>
          </div>

          {selected.columns ? (
            <div>
              <h4>Column mapping</h4>
              <table className="datasets__table">
                <tbody>
                  <tr>
                    <th scope="row">Input (question)</th>
                    <td>{mappingValue(selected.columns.input_column)}</td>
                  </tr>
                  <tr>
                    <th scope="row">Output (answer)</th>
                    <td>{mappingValue(selected.columns.output_column)}</td>
                  </tr>
                  <tr>
                    <th scope="row">ID</th>
                    <td>{mappingValue(selected.columns.id_column)}</td>
                  </tr>
                  <tr>
                    <th scope="row">Retrieved context</th>
                    <td>{mappingValue(selected.columns.retrieved_context_column)}</td>
                  </tr>
                  <tr>
                    <th scope="row">Latency (ms)</th>
                    <td>{mappingValue(selected.columns.latency_ms_column)}</td>
                  </tr>
                  <tr>
                    <th scope="row">Tokens in / out</th>
                    <td>
                      {mappingValue(selected.columns.tokens_in_column)} /{" "}
                      {mappingValue(selected.columns.tokens_out_column)}
                    </td>
                  </tr>
                </tbody>
              </table>
              <p className="card__hint">
                {selected.columns.detected
                  ? "Detected automatically from the file's header row."
                  : "Set manually at upload time."}
              </p>
            </div>
          ) : (
            <p className="card__hint">No column mapping stored for this dataset.</p>
          )}

          <h4 style={{ marginTop: "var(--space-5)" }}>Generate more cases with the LLM</h4>
          {providers.length === 0 ? (
            <p className="card__hint">
              No active provider yet — add one in Providers and models first (Ollama works out of
              the box).
            </p>
          ) : (
            <form onSubmit={handleGenerate} className="datasets__upload">
              <label className="form__label" htmlFor="generate-provider">
                Provider:
              </label>
              <select
                id="generate-provider"
                data-testid="generate-provider"
                value={generateProviderId}
                onChange={(e) => setGenerateProviderId(e.target.value)}
                disabled={busy}
                required
              >
                <option value="">Choose a provider…</option>
                {providers.map((provider) => (
                  <option key={provider.id} value={provider.id}>
                    {provider.name} ({provider.model_name})
                  </option>
                ))}
              </select>
              <label className="form__label" htmlFor="generate-count">
                Number of cases (1–100):
              </label>
              <input
                id="generate-count"
                data-testid="generate-count"
                type="number"
                min={1}
                max={100}
                value={generateCount}
                onChange={(e) => setGenerateCount(Number(e.target.value))}
                disabled={busy}
              />
              <label className="form__label" htmlFor="generate-source">
                Optional source text (up to 50,000 characters):
              </label>
              <textarea
                id="generate-source"
                data-testid="generate-source"
                rows={3}
                value={sourceText}
                maxLength={50_000}
                onChange={(e) => {
                  setSourceText(e.target.value);
                  if (e.target.value) {
                    setSourceFile(null);
                    const fileInput = document.getElementById(
                      "generate-source-file",
                    ) as HTMLInputElement | null;
                    if (fileInput) fileInput.value = "";
                  }
                }}
                placeholder="Paste notes, a policy, or a product description…"
                disabled={busy}
              />
              <label className="form__label" htmlFor="generate-source-file">
                Or upload a source file (PDF, TXT or MD; 5 MB maximum):
              </label>
              <input
                id="generate-source-file"
                data-testid="generate-source-file"
                type="file"
                accept=".pdf,.txt,.md,application/pdf,text/plain,text/markdown"
                onChange={(e) => {
                  const picked = e.target.files?.[0] ?? null;
                  setSourceFile(picked);
                  if (picked) setSourceText("");
                }}
                disabled={busy}
              />
              <p className="card__hint">
                Sources are split into at most 20 passages. Text beyond that limit is omitted and
                reported after generation. Scanned PDFs without selectable text cannot be used.
              </p>
              <div className="datasets__actions" style={{ marginTop: "var(--space-3)" }}>
                <Button
                  type="submit"
                  variant="primary"
                  loading={busy}
                  disabled={!generateProviderId}
                  data-testid="generate-submit"
                >
                  {busy ? <Spinner size="sm" label="Generating" /> : "Generate draft"}
                </Button>
              </div>
              <p className="card__hint">
                Generation creates a new draft version; nothing is used in runs until you approve
                it.
              </p>
            </form>
          )}

          <h4 style={{ marginTop: "var(--space-5)" }}>Versions</h4>
          <table className="datasets__table">
            <thead>
              <tr>
                <th scope="col">#</th>
                <th scope="col">Rows</th>
                <th scope="col">Hash</th>
                <th scope="col">Source</th>
                <th scope="col">Status</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {versions.map((version) => (
                <tr key={version.id}>
                  <td>{version.version_no}</td>
                  <td>{version.row_count}</td>
                  <td>
                    <code title={version.content_hash}>{shortHash(version.content_hash)}</code>
                  </td>
                  <td>
                    {version.generated ? (
                      <span className="badge badge--review">Generated</span>
                    ) : (
                      <span className="badge badge--neutral">Uploaded</span>
                    )}
                  </td>
                  <td>
                    {version.approved_at ? (
                      <span className="badge badge--go">Approved</span>
                    ) : (
                      <span className="badge badge--neutral">Draft</span>
                    )}
                  </td>
                  <td>
                    <div className="datasets__actions">
                      <Button
                        variant="secondary"
                        onClick={() => void handlePreview(version.version_no)}
                      >
                        Preview
                      </Button>
                      {!version.approved_at && (
                        <Button
                          variant="primary"
                          onClick={() => void handleApprove(version.version_no)}
                          data-testid="approve-version"
                        >
                          Approve
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {preview && (
            <div style={{ marginTop: "var(--space-5)" }} data-testid="dataset-preview">
              <h4>Preview — version {preview.versionNo}</h4>
              {preview.items.length === 0 ? (
                <p className="card__hint">This version has no items.</p>
              ) : (
                <table className="datasets__table">
                  <thead>
                    <tr>
                      <th scope="col">#</th>
                      <th scope="col">Question</th>
                      <th scope="col">Answer</th>
                      <th scope="col">Context / reference passage</th>
                      <th scope="col">Category</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.items.map((item) => (
                      <tr key={item.id}>
                        <td>{item.row_index}</td>
                        <td>{String(item.data.question ?? "—")}</td>
                        <td>{String(item.data.answer ?? "—")}</td>
                        <td data-testid="preview-passage">
                          {item.data.reference_context
                            ? String(item.data.reference_context)
                            : item.data.context
                              ? String(item.data.context)
                              : "—"}
                        </td>
                        <td>{item.data.category ? String(item.data.category) : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
