import { Button } from "./Button";
import type { TargetCheck } from "../lib/targets";

interface AnswerCandidate {
  path: string;
  preview: string;
}

export interface WebsiteWizardProps {
  curlText: string;
  onCurlChange: (value: string) => void;
  message: string;
  onMessageChange: (value: string) => void;
  onRead: () => void | Promise<void>;
  canRead: boolean;
  busy: boolean;
  error: string | null;
  check: TargetCheck | null;
  candidates: AnswerCandidate[];
  selectedPath: string;
  onSelectPath: (path: string) => void;
  accepted: boolean;
  onAccept: (checked: boolean) => void | Promise<void>;
  headerNames: string[];
  onClose: () => void;
}

export function WebsiteWizard({
  curlText,
  onCurlChange,
  message,
  onMessageChange,
  onRead,
  canRead,
  busy,
  error,
  check,
  candidates,
  selectedPath,
  onSelectPath,
  accepted,
  onAccept,
  headerNames,
  onClose,
}: WebsiteWizardProps) {
  return (
    <section
      className="card"
      data-testid="website-wizard"
      style={{ marginTop: "var(--space-4)" }}
    >
      <div className="card__header">
        <h2>Website chatbot</h2>
      </div>
      <ol>
        <li>Open the website&apos;s chatbot in your browser.</li>
        <li>Open DevTools → Network and send one normal message.</li>
        <li>Right-click the request that carries your message (fetch/XHR) → Copy → Copy as cURL.</li>
        <li>Paste it below and type the exact message you sent.</li>
      </ol>
      <p className="form__hint">Use a test account, never real customer data.</p>
      <p className="form__hint">
        Only test a website you have permission to test. Confirm permission below before reading it.
      </p>
      <p className="form__hint">Attack probes stay off for remote websites.</p>

      <div style={{ marginTop: "var(--space-3)" }}>
        <label className="form__label" htmlFor="website-curl">
          Paste the cURL command:
        </label>
        <textarea
          id="website-curl"
          data-testid="website-curl"
          rows={4}
          value={curlText}
          onChange={(event) => onCurlChange(event.target.value)}
          placeholder="curl ..."
          disabled={busy}
        />
      </div>

      <div style={{ marginTop: "var(--space-3)" }}>
        <label className="form__label" htmlFor="website-message">
          The exact message you sent:
        </label>
        <input
          id="website-message"
          data-testid="website-message"
          type="text"
          value={message}
          onChange={(event) => onMessageChange(event.target.value)}
          disabled={busy}
        />
      </div>

      {headerNames.length > 0 ? (
        <p className="form__hint" data-testid="website-imported-headers">
          Imported headers: {headerNames.map((name) => `${name}: XXXX`).join(", ")}
        </p>
      ) : null}

      <div style={{ marginTop: "var(--space-3)" }}>
        <Button
          variant="secondary"
          onClick={() => void onRead()}
          loading={busy}
          disabled={!canRead || busy}
          data-testid="website-read"
        >
          Read it
        </Button>
      </div>

      {error ? (
        <p className="form-error" role="alert" style={{ marginTop: "var(--space-2)" }}>
          {error}
        </p>
      ) : null}

      {check ? (
        <div className="notice" role="status" style={{ marginTop: "var(--space-3)" }}>
          <strong>Checked the target</strong>
          <div style={{ marginTop: "var(--space-2)" }}>
            <div data-testid="website-check-status">
              {check.status === null ? "No HTTP answer" : `HTTP ${check.status}`} ·{" "}
              {check.latency_ms === null ? "no timing" : `${check.latency_ms} ms`} ·{" "}
              {check.mapping_path ? `path ${check.mapping_path}` : "pick an answer field below"}
            </div>
            <pre
              data-testid="website-check-answer"
              style={{ whiteSpace: "pre-wrap", maxHeight: "160px", overflow: "auto" }}
            >
              {check.answer || "(no answer text)"}
            </pre>
            {check.question_path_reason ? (
              <p className="form-error" data-testid="website-question-path-reason">
                {check.question_path_reason}
              </p>
            ) : null}
            {candidates.length > 0 ? (
              <fieldset style={{ marginTop: "var(--space-2)" }}>
                <legend className="form__label">Pick the answer field:</legend>
                {candidates.map((candidate, index) => (
                  <label
                    key={candidate.path}
                    style={{ display: "block", marginTop: "var(--space-1)" }}
                  >
                    <input
                      type="radio"
                      name="website-answer-candidate"
                      data-testid={`website-candidate-${index}`}
                      value={candidate.path}
                      checked={selectedPath === candidate.path}
                      onChange={() => onSelectPath(candidate.path)}
                      disabled={busy}
                    />{" "}
                    <strong>{candidate.path}</strong>: {candidate.preview}
                  </label>
                ))}
              </fieldset>
            ) : null}
          </div>
          {check.extraction_ok ? (
            <div style={{ marginTop: "var(--space-2)" }}>
              <label style={{ display: "block" }}>
                <input
                  type="checkbox"
                  data-testid="website-accept"
                  checked={accepted}
                  onChange={(event) => void onAccept(event.target.checked)}
                  disabled={
                    busy ||
                    !selectedPath ||
                    check.mapping_path !== selectedPath ||
                    !check.question_path
                  }
                />{" "}
                This extraction looks right
              </label>
            </div>
          ) : null}
        </div>
      ) : null}

      <div style={{ marginTop: "var(--space-3)" }}>
        <Button variant="secondary" onClick={onClose} disabled={busy}>
          Close
        </Button>
      </div>
    </section>
  );
}
