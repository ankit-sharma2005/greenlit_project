import type { RunSummary as RunSummaryData } from "../lib/runs";

/**
 * The finished run in plain words (same block the HTML export prints).
 *
 * The sentences come from the backend's template builder, so the page and the
 * export cannot drift: nothing here is written per run, and a metric that was
 * never measured is listed by name instead of being shown as a score.
 */
export function RunSummary({ summary }: { summary: RunSummaryData }) {
  return (
    <section
      className="card run-summary"
      aria-labelledby="run-summary-heading"
      data-testid="run-summary"
    >
      <div className="card__header">
        <h2 id="run-summary-heading">In plain words</h2>
      </div>

      <p className="run-summary__headline" data-testid="run-summary-headline">
        {summary.headline}
      </p>

      {summary.reasons.length > 0 ? (
        <>
          <h3 className="run-summary__heading">Why</h3>
          <ul className="run-summary__list" data-testid="run-summary-reasons">
            {summary.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </>
      ) : null}

      <p data-testid="run-summary-weakest">{summary.weakest_sentence}</p>

      {summary.not_measured_sentence ? (
        <p className="card__hint" data-testid="run-summary-not-measured">
          {summary.not_measured_sentence}
        </p>
      ) : null}

      <p data-testid="run-summary-safety">{summary.safety_sentence}</p>

      {summary.next_steps.length > 0 ? (
        <>
          <h3 className="run-summary__heading">What to try next</h3>
          <ol className="run-summary__list" data-testid="run-summary-next">
            {summary.next_steps.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
        </>
      ) : null}
    </section>
  );
}
