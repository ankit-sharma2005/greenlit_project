import { type RunOperations } from "../lib/runs";

/**
 * How the app behaved during the run: speed, reliability and token use.
 *
 * Everything is rendered through the same "unmeasured" helper so a null never
 * turns into a convincing `0`. A rate nobody could measure is not a zero rate,
 * and a run that never reported tokens did not use none.
 */

function latency(value: number | null): string {
  return value === null ? "not measured" : `${Math.round(value)} ms`;
}

function rate(value: number | null): string {
  return value === null ? "not measured" : `${(value * 100).toFixed(1)}%`;
}

function tokens(value: number | null): string {
  return value === null ? "not reported" : value.toLocaleString("en-US");
}

function cost(operations: RunOperations): string {
  if (!operations.cost_configured) {
    return "not configured";
  }
  if (operations.cost_estimate === null) {
    return "not reported";
  }
  return `~$${operations.cost_estimate.toFixed(4)}`;
}

export interface OperationsPanelProps {
  operations: RunOperations | null | undefined;
}

export function OperationsPanel({ operations }: OperationsPanelProps) {
  if (!operations) {
    return null;
  }

  const rows: Array<{ label: string; value: string; testId: string }> = [
    {
      label: "Cases attempted",
      value: String(operations.items_attempted),
      testId: "ops-attempted",
    },
    { label: "p50 latency", value: latency(operations.latency_p50_ms), testId: "ops-p50" },
    { label: "p95 latency", value: latency(operations.latency_p95_ms), testId: "ops-p95" },
    { label: "Error rate", value: rate(operations.error_rate), testId: "ops-error-rate" },
    { label: "Timeout rate", value: rate(operations.timeout_rate), testId: "ops-timeout-rate" },
    { label: "Tokens in", value: tokens(operations.tokens_in_total), testId: "ops-tokens-in" },
    { label: "Tokens out", value: tokens(operations.tokens_out_total), testId: "ops-tokens-out" },
    { label: "Estimated cost", value: cost(operations), testId: "ops-cost" },
  ];

  return (
    <section className="card" aria-labelledby="operations-heading" data-testid="run-operations">
      <div className="card__header">
        <h2 id="operations-heading">Operations</h2>
      </div>
      <p className="card__hint">
        Latency is measured per case as the app answered. A value nobody reported is shown as
        unmeasured rather than as zero.
      </p>
      <dl className="metric-list">
        {rows.map((row) => (
          <div className="metric-list__row" key={row.testId}>
            <dt>{row.label}</dt>
            <dd data-testid={row.testId}>{row.value}</dd>
          </div>
        ))}
      </dl>
      {operations.latency_samples > 0 && (
        <p className="card__hint" data-testid="ops-samples">
          Based on {operations.latency_samples} measured{" "}
          {operations.latency_samples === 1 ? "case" : "cases"}.
        </p>
      )}
    </section>
  );
}
