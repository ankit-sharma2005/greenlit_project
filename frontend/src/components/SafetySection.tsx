import type { MetricRow } from "../lib/evaluations";

const ATTACK_RESISTED = "attack_resisted";
const OVER_REFUSAL = "over_refusal";

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function asList(value: unknown): string[] {
  return Array.isArray(value) ? value.map((entry) => String(entry)) : [];
}

function share(value: number | null): string {
  return value === null ? "—" : value.toFixed(2);
}

/**
 * The built-in safety results as their own section (spec 8.3).
 *
 * The metric table already lists `attack_resisted` and `over_refusal` as rows;
 * this section answers the question a person actually asks: how many attacks
 * were tried, how many were resisted, how often harmless requests were refused,
 * and which critical checks failed. It renders nothing when the run was not
 * probed, so a run without Safety stays exactly as it was.
 */
export function SafetySection({ metrics }: { metrics: MetricRow[] }) {
  const attacks = metrics.find((metric) => metric.name === ATTACK_RESISTED);
  const overRefusal = metrics.find((metric) => metric.name === OVER_REFUSAL);
  if (!attacks && !overRefusal) return null;

  const attackDetails = attacks?.details ?? {};
  const tried = asNumber(attackDetails.attacks) ?? 0;
  const resisted = asNumber(attackDetails.resisted) ?? 0;
  const criticalFailures = asList(attackDetails.critical_failures);
  const leaked = asList(attackDetails.leaked_marker_cases);
  const attackVersion = attackDetails.set_version;

  const refusalDetails = overRefusal?.details ?? {};
  const prompts = asNumber(refusalDetails.prompts) ?? 0;
  const refused = asNumber(refusalDetails.refused) ?? 0;
  const refusedShare = asNumber(refusalDetails.over_refusal_share);
  const setVersion = refusalDetails.set_version ?? attackVersion;

  const probed = attacks?.instrumented ?? false;

  return (
    <section
      className="card"
      aria-labelledby="safety-heading"
      data-testid="safety-section"
      style={{ marginTop: "var(--space-5)" }}
    >
      <div className="card__header">
        <h2 id="safety-heading">Safety</h2>
        <span className="badge badge--neutral">
          {setVersion ? `attack set ${String(setVersion)}` : "built-in set"}
        </span>
      </div>

      {!probed ? (
        <p className="card__hint" data-testid="safety-not-probed">
          {attacks?.explanation ?? "The app was not probed with the built-in safety sets."}
        </p>
      ) : (
        <table className="results__table" data-testid="safety-table">
          <thead>
            <tr>
              <th scope="col">Check</th>
              <th scope="col">Result</th>
              <th scope="col">Why</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Attacks tried</td>
              <td className="results__metric-score" data-testid="safety-attacks">
                {tried}
              </td>
              <td>
                prompt injection, hidden instructions, system-prompt leaks, jailbreaks and
                disallowed requests
              </td>
            </tr>
            <tr>
              <td>Attacks resisted</td>
              <td
                className={attacks?.passed ? "results__state--pass" : "results__state--fail"}
                data-testid="safety-resisted"
              >
                {resisted} of {tried}
              </td>
              <td>{attacks?.explanation}</td>
            </tr>
            <tr>
              <td>Over-refusal</td>
              <td
                className={
                  overRefusal?.passed === false ? "results__state--fail" : "results__state--pass"
                }
                data-testid="safety-over-refusal"
              >
                {share(refusedShare)}
              </td>
              <td>
                {refused} of {prompts} harmless requests were refused
                {overRefusal?.instrumented === false ? " (the safe prompts were not sent)" : ""}
              </td>
            </tr>
            <tr>
              <td>Critical checks failed</td>
              <td
                className={
                  criticalFailures.length > 0 ? "results__state--fail" : "results__state--pass"
                }
                data-testid="safety-critical"
              >
                {criticalFailures.length}
              </td>
              <td data-testid="safety-critical-detail">
                {criticalFailures.length > 0
                  ? `a leaked secret or a missing refusal is a hard NO-GO: ${criticalFailures.join(", ")}`
                  : "no critical attack succeeded"}
              </td>
            </tr>
          </tbody>
        </table>
      )}

      {leaked.length > 0 ? (
        <p className="form-error" role="alert" data-testid="safety-leaks">
          The app repeated the planted marker in {leaked.join(", ")}.
        </p>
      ) : null}
    </section>
  );
}
