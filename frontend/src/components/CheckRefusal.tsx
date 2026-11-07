import type { TargetCheckError } from "../lib/targets";

/** Plain words for each code the server can name, so the code is not the message. */
const KIND_LABELS: Record<string, string> = {
  blocked_by_site: "The site blocked this request",
  csrf_rejected: "The site rejected the CSRF token",
  auth_error: "The site needs a signed-in session",
  http_error: "The site answered with an error",
};

/**
 * One refused request, explained: what the person should do (the server's
 * summary), which code it was named as, and the evidence it was named from.
 *
 * The evidence is response headers and body markers, already allowlisted and
 * redacted on the server: no cookie or token ever reaches this component.
 */
export function CheckRefusal({ error }: { error: TargetCheckError }) {
  // ``kind`` is the shared family (every 401/403 is http_error); ``code`` is
  // what the refusal actually was, so that is what the person is shown.
  const code = error.code ?? error.kind;
  const label = KIND_LABELS[code] ?? "The request failed";
  const headers = Object.entries(error.headers ?? {});
  return (
    <div data-testid="check-refusal" style={{ marginTop: "var(--space-2)" }}>
      <p className="form-error" data-testid="check-refusal-summary">
        {error.summary}
      </p>
      <p className="form__hint" data-testid="check-refusal-kind">
        {label} ({code}
        {error.status === null ? "" : `, HTTP ${error.status}`})
      </p>
      {error.evidence && error.evidence.length > 0 ? (
        <ul className="form__hint" data-testid="check-refusal-evidence">
          {error.evidence.map((line, index) => (
            <li key={`${index}-${line}`}>{line}</li>
          ))}
        </ul>
      ) : null}
      {headers.length > 0 ? (
        <p className="form__hint" data-testid="check-refusal-headers">
          {headers.map(([name, value]) => `${name}: ${value}`).join(" · ")}
        </p>
      ) : null}
    </div>
  );
}
