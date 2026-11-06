import { useCallback, useEffect, useState } from "react";

import { ApiError } from "../lib/api";
import {
  createSavedTarget,
  deleteSavedTarget,
  listSavedTargets,
  updateSavedTarget,
  type ResponseFormat,
  type SavedTarget,
  type SavedTargetPayload,
} from "../lib/savedTargets";
import { Button } from "./Button";
import { Spinner } from "./Spinner";

const FORMATS: ResponseFormat[] = ["json", "sse", "ndjson", "text"];

const FORMAT_LABELS: Record<ResponseFormat, string> = {
  json: "One JSON body",
  sse: "Server-sent events",
  ndjson: "Newline-delimited JSON",
  text: "Plain text",
};

interface FormState {
  name: string;
  url: string;
  method: string;
  responseFormat: ResponseFormat;
  answerPath: string;
  contextPath: string;
  timeoutSeconds: string;
  bodyTemplate: string;
}

const EMPTY_FORM: FormState = {
  name: "",
  url: "",
  method: "POST",
  responseFormat: "json",
  answerPath: "",
  contextPath: "",
  timeoutSeconds: "60",
  bodyTemplate: "",
};

function formOf(target: SavedTarget): FormState {
  return {
    name: target.name,
    url: target.url,
    method: target.method,
    responseFormat: target.response_format,
    answerPath: target.answer_path ?? "",
    contextPath: target.context_path ?? "",
    timeoutSeconds: String(target.timeout_seconds),
    bodyTemplate: target.body_template ?? "",
  };
}

/**
 * Settings → Connectors: the targets somebody actually tests, kept so their
 * request/response format survives a reload.
 *
 * The shelf holds no header value and no permission record: a pasted cURL's
 * headers stay encrypted inside the run that sent them, and permission to test a
 * remote app is still asked per run by the first-contact check.
 */
export function ConnectorsPanel() {
  const [targets, setTargets] = useState<SavedTarget[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [editingId, setEditingId] = useState<string | null>(null);

  const showError = (caught: unknown) => {
    setError(caught instanceof ApiError ? caught.message : "Something went wrong. Try again.");
  };

  const refresh = useCallback(async () => {
    try {
      const next = await listSavedTargets();
      setTargets(next.items);
    } catch (caught) {
      showError(caught);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((current) => ({ ...current, [key]: value }));

  const handleEdit = (target: SavedTarget) => {
    setError(null);
    setNotice(null);
    setEditingId(target.id);
    setForm(formOf(target));
  };

  const handleCancel = () => {
    setEditingId(null);
    setForm(EMPTY_FORM);
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setNotice(null);
    setBusy(true);

    const payload: SavedTargetPayload = {
      name: form.name.trim(),
      url: form.url.trim(),
      method: form.method,
      response_format: form.responseFormat,
      // An empty box means "no such field", which the API stores as null.
      answer_path: form.answerPath.trim() || null,
      context_path: form.contextPath.trim() || null,
      body_template: form.bodyTemplate.trim() || null,
      timeout_seconds: Number(form.timeoutSeconds) || 60,
    };

    try {
      if (editingId) {
        const saved = await updateSavedTarget(editingId, payload);
        setNotice(`“${saved.name}” was updated.`);
      } else {
        const saved = await createSavedTarget(payload);
        setNotice(`“${saved.name}” is saved.`);
      }
      setEditingId(null);
      setForm(EMPTY_FORM);
      await refresh();
    } catch (caught) {
      showError(caught);
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async (target: SavedTarget) => {
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      await deleteSavedTarget(target.id);
      if (editingId === target.id) handleCancel();
      setNotice(`“${target.name}” was deleted.`);
      await refresh();
    } catch (caught) {
      showError(caught);
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <section className="card" data-testid="connectors-panel">
        <Spinner size="md" label="Loading saved targets" />
      </section>
    );
  }

  return (
    <section className="card" aria-labelledby="connectors-heading" data-testid="connectors-panel">
      <div className="card__header">
        <h2 id="connectors-heading">Connectors</h2>
        <span className="badge badge--neutral">targets {targets.length}</span>
      </div>
      <p className="card__hint">
        A saved target keeps where your app lives and the format GreenLit reads it with: the method,
        the answer and context paths, and how the answer arrives. Header values are never stored
        here — a cURL&apos;s headers stay encrypted inside the run that sent them — and permission
        to test a remote app is still asked each time you start a run.
      </p>

      {error ? (
        <p className="form-error" role="alert" data-testid="connectors-error">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="form-success" role="status" data-testid="connectors-notice">
          {notice}
        </p>
      ) : null}

      <form onSubmit={(event) => void handleSubmit(event)} style={{ marginTop: "var(--space-4)" }}>
        <h3>{editingId ? "Edit this target" : "Save a target"}</h3>

        <div className="form__field">
          <label className="form__label" htmlFor="connector-name">
            Name:
          </label>
          <input
            id="connector-name"
            data-testid="connector-name"
            value={form.name}
            onChange={(event) => set("name", event.target.value)}
            placeholder="Support bot"
            disabled={busy}
          />
        </div>

        <div className="form__field">
          <label className="form__label" htmlFor="connector-url">
            URL:
          </label>
          <input
            id="connector-url"
            data-testid="connector-url"
            value={form.url}
            onChange={(event) => set("url", event.target.value)}
            placeholder="https://myapp.example.com/ask"
            disabled={busy}
          />
        </div>

        <div className="form__field">
          <label className="form__label" htmlFor="connector-method">
            Method:
          </label>
          <select
            id="connector-method"
            data-testid="connector-method"
            value={form.method}
            onChange={(event) => set("method", event.target.value)}
            disabled={busy}
          >
            <option value="POST">POST</option>
            <option value="GET">GET</option>
            <option value="PUT">PUT</option>
          </select>
        </div>

        <div className="form__field">
          <label className="form__label" htmlFor="connector-format">
            Answer arrives as:
          </label>
          <select
            id="connector-format"
            data-testid="connector-format"
            value={form.responseFormat}
            onChange={(event) => set("responseFormat", event.target.value as ResponseFormat)}
            disabled={busy}
          >
            {FORMATS.map((format) => (
              <option key={format} value={format}>
                {FORMAT_LABELS[format]}
              </option>
            ))}
          </select>
        </div>

        <div className="form__field">
          <label className="form__label" htmlFor="connector-answer-path">
            Answer path:
          </label>
          <input
            id="connector-answer-path"
            data-testid="connector-answer-path"
            value={form.answerPath}
            onChange={(event) => set("answerPath", event.target.value)}
            placeholder="$.answer"
            disabled={busy}
          />
          <p className="form__hint">
            Where the answer sits in the response. Empty means the whole body.
          </p>
        </div>

        <div className="form__field">
          <label className="form__label" htmlFor="connector-context-path">
            Context path:
          </label>
          <input
            id="connector-context-path"
            data-testid="connector-context-path"
            value={form.contextPath}
            onChange={(event) => set("contextPath", event.target.value)}
            placeholder="$.sources"
            disabled={busy}
          />
          <p className="form__hint">
            Optional. A retrieved-context field turns on the groundedness checks.
          </p>
        </div>

        <div className="form__field">
          <label className="form__label" htmlFor="connector-body">
            Request body:
          </label>
          <textarea
            id="connector-body"
            data-testid="connector-body"
            value={form.bodyTemplate}
            onChange={(event) => set("bodyTemplate", event.target.value)}
            placeholder={'{"question": "{{question}}"}'}
            rows={3}
            disabled={busy}
          />
          <p className="form__hint">
            Use <code>{"{{question}}"}</code> where each test question goes. Empty sends
            GreenLit&apos;s default body.
          </p>
        </div>

        <div className="form__field">
          <label className="form__label" htmlFor="connector-timeout">
            Timeout (seconds):
          </label>
          <input
            id="connector-timeout"
            data-testid="connector-timeout"
            type="number"
            min={1}
            max={300}
            value={form.timeoutSeconds}
            onChange={(event) => set("timeoutSeconds", event.target.value)}
            disabled={busy}
          />
        </div>

        <div className="datasets__actions">
          <Button type="submit" variant="primary" loading={busy} data-testid="connector-save">
            {editingId ? "Save changes" : "Save target"}
          </Button>
          {editingId ? (
            <Button
              type="button"
              variant="secondary"
              onClick={handleCancel}
              disabled={busy}
              data-testid="connector-cancel"
            >
              Cancel
            </Button>
          ) : null}
        </div>
      </form>

      <h3 style={{ marginTop: "var(--space-5)" }}>Saved targets</h3>
      {targets.length === 0 ? (
        <p className="card__hint" data-testid="connectors-none">
          Nothing saved yet. A target you save here keeps the format you detected on the New Test
          page, so you do not have to work it out again.
        </p>
      ) : (
        <table className="results__table" data-testid="connectors-table">
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Target</th>
              <th scope="col">Format</th>
              <th scope="col">Answer path</th>
              <th scope="col">Actions</th>
            </tr>
          </thead>
          <tbody>
            {targets.map((target) => (
              <tr key={target.id} data-testid={`connector-row-${target.name}`}>
                <td>{target.name}</td>
                <td>
                  <code>
                    {target.method} {target.url}
                  </code>
                  {target.allow_private_targets ? (
                    <span className="card__hint"> · on this computer</span>
                  ) : null}
                </td>
                <td>{FORMAT_LABELS[target.response_format] ?? target.response_format}</td>
                <td>
                  {target.answer_path ? (
                    <code>{target.answer_path}</code>
                  ) : (
                    <span className="card__hint">whole body</span>
                  )}
                </td>
                <td>
                  <div className="datasets__actions">
                    <Button
                      type="button"
                      variant="secondary"
                      onClick={() => handleEdit(target)}
                      disabled={busy}
                      data-testid={`connector-edit-${target.name}`}
                    >
                      Edit
                    </Button>
                    <Button
                      type="button"
                      variant="secondary"
                      onClick={() => void handleDelete(target)}
                      disabled={busy}
                      data-testid={`connector-delete-${target.name}`}
                    >
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
  );
}
