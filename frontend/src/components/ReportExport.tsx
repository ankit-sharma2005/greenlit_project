import { useState } from "react";

import { Button } from "./Button";
import { API_BASE_URL } from "../lib/api";

/**
 * The three report formats (spec 8.5).
 *
 * The download goes through `fetch` with the session cookie rather than a plain
 * link, so a failure (an expired session, a deleted run) surfaces as a message
 * instead of opening a broken tab. The file itself is produced by the API: this
 * component never assembles a report, so an export cannot disagree with the
 * verdict card it sits under.
 */
const FORMATS = [
  { format: "html", label: "HTML", hint: "self-contained and printable" },
  { format: "json", label: "JSON", hint: "the full result" },
  { format: "csv", label: "CSV", hint: "one row per case" },
] as const;

export interface ReportExportProps {
  runId: string;
}

export function ReportExport({ runId }: ReportExportProps) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function download(format: string) {
    setBusy(format);
    setError(null);
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/runs/${runId}/report?format=${format}`, {
        credentials: "include",
      });
      if (!response.ok) {
        throw new Error(
          response.status === 404
            ? "This run is not available to your account any more."
            : `The export failed (HTTP ${response.status}).`,
        );
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `greenlit-run-${runId}.${format}`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not export this run. Try again.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="report-export" style={{ marginTop: "var(--space-4)" }}>
      <span className="verdict__label">Export report</span>
      <div className="datasets__actions" style={{ marginTop: "var(--space-2)" }}>
        {FORMATS.map((entry) => (
          <Button
            key={entry.format}
            variant="secondary"
            onClick={() => void download(entry.format)}
            loading={busy === entry.format}
            disabled={busy !== null}
            data-testid={`export-${entry.format}`}
            title={entry.hint}
          >
            {entry.label}
          </Button>
        ))}
      </div>
      <p className="form__hint" data-testid="export-hint">
        The report holds the setup, the verdict and rule, every metric (with “not instrumented”
        spelled out), the failed cases, the safety results and the judge that scored it. Request
        headers are redacted; no key is ever exported.
      </p>
      {error ? (
        <p className="form-error" role="alert" data-testid="export-error">
          {error}
        </p>
      ) : null}
    </div>
  );
}
