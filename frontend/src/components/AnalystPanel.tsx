import { useEffect, useState } from "react";

import { ApiError } from "../lib/api";
import {
  explainRun,
  getExplanation,
  previewExplanation,
  type Explanation,
  type ExplanationPreview,
} from "../lib/analyst";
import { Button } from "./Button";

const LABEL = "AI explanation. It may be wrong and does not affect the verdict.";

function messageOf(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error ? error.message : "Something went wrong.";
}

/**
 * "Explain this run": shows the exact input first, asks for an extra confirmation when the
 * analyst provider is remote, and renders the answer as plain text only.
 *
 * The model's words are never parsed for numbers or turned into markup: the verdict above is
 * the one that decided the run.
 */
export function AnalystPanel({ runId }: { runId: string }) {
  const [preview, setPreview] = useState<ExplanationPreview | null>(null);
  const [unavailable, setUnavailable] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Explanation | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    previewExplanation(runId)
      .then((body) => {
        if (active) setPreview(body);
      })
      .catch((problem: unknown) => {
        if (active) setUnavailable(messageOf(problem));
      });
    getExplanation(runId)
      .then((body) => {
        if (active) setResult(body);
      })
      .catch(() => {
        /* No stored explanation is a normal state, not an error to show. */
      });
    return () => {
      active = false;
    };
  }, [runId]);

  const remote = preview !== null && !preview.provider_is_local;
  const needsConfirmation = remote && !confirmed;

  async function explain() {
    setBusy(true);
    setError(null);
    try {
      setResult(await explainRun(runId, remote));
    } catch (problem: unknown) {
      setError(messageOf(problem));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel" data-testid="analyst-panel" aria-labelledby="analyst-heading">
      <h2 id="analyst-heading">Explain this run</h2>
      <p className="muted">
        A model reads a summary of this run and writes a few sentences about what drove the
        verdict. The verdict itself is decided by fixed rules and is not changed.
      </p>

      {unavailable ? (
        <p className="notice" data-testid="analyst-unavailable">
          {unavailable}
        </p>
      ) : null}

      {preview ? (
        <>
          <details data-testid="analyst-preview">
            <summary>Show exactly what will be sent</summary>
            <pre data-testid="analyst-preview-input">{preview.input}</pre>
          </details>
          <p className="muted" data-testid="analyst-provider-note">
            {preview.provider_name} · {preview.model}
            {remote ? " (remote: this leaves your machine)" : " (local)"}
          </p>
          {remote ? (
            <label className="form__label" htmlFor="analyst-confirm-remote">
              <input
                id="analyst-confirm-remote"
                type="checkbox"
                data-testid="analyst-confirm-remote"
                checked={confirmed}
                onChange={(event) => setConfirmed(event.target.checked)}
              />{" "}
              I understand this summary is sent to {preview.provider_name}.
            </label>
          ) : null}
          <Button
            onClick={() => void explain()}
            disabled={busy || needsConfirmation}
            data-testid="analyst-explain"
          >
            {busy ? "Explaining…" : "Explain this run"}
          </Button>
        </>
      ) : null}

      {error ? (
        <p className="notice" role="status" data-testid="analyst-error">
          {error}
        </p>
      ) : null}

      {result && result.status === "ok" ? (
        <div data-testid="analyst-explanation">
          <p className="muted">{LABEL}</p>
          <p data-testid="analyst-text">{result.text}</p>
          <p className="muted" data-testid="analyst-model">
            {result.provider_name ?? "unknown provider"} · {result.model ?? "unknown model"} ·{" "}
            {result.prompt_version ?? ""}
          </p>
        </div>
      ) : null}

      {result && result.status !== "ok" && result.status !== "none" ? (
        <p className="notice" role="status" data-testid="analyst-rejected">
          {result.message || "The explanation was not shown."}
        </p>
      ) : null}
    </section>
  );
}
