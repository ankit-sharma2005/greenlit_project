import { useEffect, useState } from "react";

import { Button } from "./Button";
import { ApiError } from "../lib/api";
import {
  acceptTargetCheck,
  checkTarget,
  type TargetCheck,
  type TargetCheckRequest,
} from "../lib/targets";

export interface TargetCheckPanelProps {
  /** Exactly the settings a full run would use; changing them voids the check. */
  request: TargetCheckRequest;
  /** The accepted check id, or null while a full run may not start. */
  onAccepted: (checkId: string | null) => void;
  disabled?: boolean;
}

/**
 * The first-contact step for a target GreenLit does not host: one harmless
 * request, the answer read through the run's own mapping, and an explicit
 * "this looks right" before a full run is allowed to start.
 */
export function TargetCheckPanel({ request, onAccepted, disabled = false }: TargetCheckPanelProps) {
  const [check, setCheck] = useState<TargetCheck | null>(null);
  const [checkedAgainst, setCheckedAgainst] = useState<string | null>(null);
  const [needsRecheck, setNeedsRecheck] = useState(false);
  const [checking, setChecking] = useState(false);
  const [accepting, setAccepting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const signature = JSON.stringify(request);
  const stale = check !== null && checkedAgainst !== null && checkedAgainst !== signature;

  // A check is bound to the settings it was made for: editing any of them means
  // the old acceptance no longer describes what the run will send.
  useEffect(() => {
    if (!stale) return;
    setCheck(null);
    setCheckedAgainst(null);
    setNeedsRecheck(true);
    onAccepted(null);
  }, [stale, onAccepted]);

  const runCheck = async () => {
    setError(null);
    setChecking(true);
    try {
      const result = await checkTarget(request);
      setCheck(result);
      setCheckedAgainst(signature);
      setNeedsRecheck(false);
      onAccepted(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not check the target.");
    } finally {
      setChecking(false);
    }
  };

  const accept = async (checked: boolean) => {
    if (check === null) return;
    if (!checked) {
      onAccepted(null);
      return;
    }
    setError(null);
    setAccepting(true);
    try {
      const accepted = await acceptTargetCheck(check.check_id);
      setCheck(accepted);
      onAccepted(accepted.accepted ? accepted.check_id : null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not accept this check.");
      onAccepted(null);
    } finally {
      setAccepting(false);
    }
  };

  return (
    <section
      className="card"
      data-testid="target-check-panel"
      style={{ marginTop: "var(--space-4)" }}
    >
      <div className="card__header">
        <h2>Check the target first</h2>
      </div>
      <p className="card__hint">
        One harmless request, sent the way the run will send it. A wrong answer path or an expired
        session then costs one request instead of a whole run. Nothing is scored.
      </p>
      <div className="datasets__actions">
        <Button
          variant="secondary"
          onClick={() => void runCheck()}
          loading={checking}
          disabled={disabled || accepting}
          data-testid="target-check-button"
        >
          {check ? "Check again" : "Check target"}
        </Button>
      </div>

      {error ? (
        <p className="form-error" role="alert" style={{ marginTop: "var(--space-2)" }}>
          {error}
        </p>
      ) : null}

      {needsRecheck && check === null ? (
        <p className="form__hint" data-testid="target-check-stale">
          The target settings changed after the check, so check again before a full run.
        </p>
      ) : null}

      {check ? (
        <div
          className="notice"
          role="status"
          data-testid="target-check-result"
          style={{ marginTop: "var(--space-3)" }}
        >
          <div data-testid="target-check-status">
            {check.status === null ? "No HTTP answer" : `HTTP ${check.status}`} ·{" "}
            {check.latency_ms === null ? "no timing" : `${check.latency_ms} ms`} ·{" "}
            {check.mapping_path ? `path ${check.mapping_path}` : "auto-detected by shape"}
          </div>
          <pre
            data-testid="target-check-answer"
            style={{ whiteSpace: "pre-wrap", maxHeight: "160px", overflow: "auto" }}
          >
            {check.answer || "(no answer text)"}
          </pre>
          {check.answer_truncated ? (
            <p className="form__hint">Shown up to 500 characters.</p>
          ) : null}
          {check.hint ? (
            <p className="form__hint" data-testid="target-check-hint">
              {check.hint}
            </p>
          ) : null}
          {check.error ? (
            <p className="form-error" data-testid="target-check-error">
              {check.error.summary}
            </p>
          ) : null}
          {check.extraction_ok ? (
            <label style={{ display: "block", marginTop: "var(--space-2)" }}>
              <input
                type="checkbox"
                data-testid="target-check-accept"
                checked={check.accepted}
                onChange={(event) => void accept(event.target.checked)}
                disabled={accepting}
              />{" "}
              This extraction looks right
            </label>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
