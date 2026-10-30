import { useEffect, useState } from "react";

import { ApiError } from "../lib/api";
import { getCriteria, type CriteriaOverview, type Criterion, type Verdict } from "../lib/criteria";
import "../styles/criteria.css";
import { Button } from "./Button";
import { Spinner } from "./Spinner";

/**
 * How the decision engine decides, read-only (Settings -> Criteria).
 *
 * Every number here comes from the engine: the thresholds, the weights, the
 * gates and the rule wording are served by /api/v1/criteria, which reads the
 * same profile the scorer uses. Nothing on this page can be edited, because a
 * run must be comparable with the runs before it.
 */

const VERDICT_LABEL: Record<Verdict, string> = {
  NO_GO: "No-Go",
  REVIEW: "Review",
  GO: "Go",
};

const VERDICT_CLASS: Record<Verdict, string> = {
  NO_GO: "badge badge--review",
  REVIEW: "badge badge--neutral",
  GO: "badge badge--go",
};

const GROUP_LABEL: Record<Criterion["group"], string> = {
  quality: "Quality",
  safety: "Safety",
  operations: "Operations",
};

function percent(value: number): string {
  return `${(value * 100).toFixed(0)}%`;
}

function weight(value: number): string {
  return value.toFixed(2);
}

function VerdictScale({ review, go }: { review: number; go: number }) {
  const bands: Array<{ verdict: Verdict; share: number; label: string }> = [
    { verdict: "NO_GO", share: review, label: `No-Go below ${review.toFixed(2)}` },
    {
      verdict: "REVIEW",
      share: Math.max(go - review, 0),
      label: `Review ${review.toFixed(2)}–${go.toFixed(2)}`,
    },
    { verdict: "GO", share: Math.max(1 - go, 0), label: `Go from ${go.toFixed(2)}` },
  ];

  return (
    <div data-testid="criteria-thresholds">
      <div className="criteria-scale" role="img" aria-label="Verdict bands by weighted score">
        {bands.map((band) => (
          <div
            key={band.verdict}
            className={`criteria-scale__band criteria-scale__band--${band.verdict.toLowerCase()}`}
            style={{ flexGrow: Math.max(band.share, 0.001) }}
            data-testid={`criteria-band-${band.verdict}`}
          >
            <span className="criteria-scale__label">{VERDICT_LABEL[band.verdict]}</span>
          </div>
        ))}
      </div>
      <p className="card__hint">
        Weighted score 0.00 → 1.00. {bands.map((band) => band.label).join(" · ")}. The bands are the
        engine's thresholds ({percent(review)} and {percent(go)}), not a drawing of their own.
      </p>
    </div>
  );
}

function MetricRow({ criterion }: { criterion: Criterion }) {
  return (
    <tr data-testid={`criteria-metric-${criterion.name}`}>
      <td>{criterion.name}</td>
      <td>
        <span className="badge badge--neutral">{GROUP_LABEL[criterion.group]}</span>
      </td>
      <td>{weight(criterion.weight)}</td>
      <td>
        {criterion.hard_gate ? (
          <span className="badge badge--review">
            hard gate at {criterion.gate_threshold?.toFixed(2)}
          </span>
        ) : (
          <span className="card__hint">—</span>
        )}
      </td>
      <td>{criterion.applies}</td>
    </tr>
  );
}

export function CriteriaPanel() {
  const [overview, setOverview] = useState<CriteriaOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getCriteria()
      .then((payload) => {
        if (!cancelled) setOverview(payload);
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        setError(
          caught instanceof ApiError ? caught.message : "Could not load the criteria. Try again.",
        );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [reloadToken]);

  if (loading) {
    return (
      <section className="card" data-testid="criteria-panel" aria-busy="true">
        <Spinner size="md" label="Loading criteria" showLabel />
      </section>
    );
  }

  if (error !== null || !overview) {
    return (
      <section className="card" data-testid="criteria-panel">
        <div className="card__header">
          <h2>Criteria</h2>
        </div>
        <p className="form-error" role="alert" data-testid="criteria-error">
          {error ?? "The criteria are not available."}
        </p>
        <Button
          variant="secondary"
          onClick={() => setReloadToken((value) => value + 1)}
          data-testid="criteria-retry"
        >
          Try again
        </Button>
      </section>
    );
  }

  return (
    <section className="card" data-testid="criteria-panel">
      <div className="card__header">
        <h2>Criteria</h2>
        <span className="badge badge--neutral">{overview.template.name}</span>
      </div>
      <p className="page__description">
        {overview.template.description} A run scores every metric it could measure, weighs them as
        below, and the decision engine applies the rules in order. The numbers are the engine's own.
      </p>

      <VerdictScale review={overview.review_threshold} go={overview.go_threshold} />

      <h3 style={{ marginTop: "var(--space-5)" }}>Metrics</h3>
      <table className="results__table" data-testid="criteria-metrics">
        <thead>
          <tr>
            <th scope="col">Metric</th>
            <th scope="col">Group</th>
            <th scope="col">Weight</th>
            <th scope="col">Hard gate</th>
            <th scope="col">Applies</th>
          </tr>
        </thead>
        <tbody>
          {overview.criteria.map((criterion) => (
            <MetricRow key={criterion.name} criterion={criterion} />
          ))}
        </tbody>
      </table>
      <p className="card__hint">
        Weights are renormalised over the metrics that were measured, so a run never has to reach a
        total the app cannot report.
      </p>

      <h3 style={{ marginTop: "var(--space-5)" }}>How the verdict is decided</h3>
      <ol className="criteria-rules" data-testid="criteria-rules">
        {overview.rules.map((rule) => (
          <li key={rule.rule} data-testid={`criteria-rule-${rule.rule}`}>
            <span className={VERDICT_CLASS[rule.verdict]}>{VERDICT_LABEL[rule.verdict]}</span>{" "}
            {rule.text}
          </li>
        ))}
      </ol>

      <div className="notice" data-testid="criteria-not-instrumented">
        <h3>Not instrumented is not zero</h3>
        <p>{overview.not_instrumented_rule}</p>
      </div>

      <p className="card__hint" data-testid="criteria-readonly-note">
        Editing criteria is not supported yet. The profiles are versioned with GreenLit — the
        available templates are {overview.templates.map((template) => template.name).join(", ")} —
        so two runs can be compared.
      </p>
    </section>
  );
}
