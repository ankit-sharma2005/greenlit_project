import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../lib/api";
import { getCompare, type CompareDetail } from "../lib/baselines";
import "../styles/results.css";

const CLASS_LABEL: Record<string, string> = {
  regressed: "Regressed",
  improved: "Improved",
  unchanged: "Unchanged (within tolerance)",
};

const CLASS_TESTID: Record<string, string> = {
  regressed: "compare-class-regressed",
  improved: "compare-class-improved",
  unchanged: "compare-class-unchanged",
};

const QUESTION_LIMIT = 80;

function shortQuestion(text: string): string {
  return text.length <= QUESTION_LIMIT ? text : `${text.slice(0, QUESTION_LIMIT - 1)}…`;
}

function signed(value: number | null): string {
  if (value === null) return "—";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}`;
}

export interface RegressionCompareProps {
  runId: string;
  baselineName: string;
}

/**
 * The compare detail below the stored PASS/WARN/BLOCK card.
 *
 * It never shows a delta for a metric that was not measured on both sides, and
 * when the two runs are not comparable it shows the reasons and no numbers at
 * all. A model-backed target always carries the noise caution, because a few
 * flipped cases can be run-to-run luck.
 */
export function RegressionCompare({ runId, baselineName }: RegressionCompareProps) {
  const [detail, setDetail] = useState<CompareDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getCompare(runId)
      .then((value) => {
        if (active) setDetail(value);
      })
      .catch((caught: unknown) => {
        if (!active) return;
        setError(
          caught instanceof ApiError ? caught.message : "The comparison could not be loaded.",
        );
      });
    return () => {
      active = false;
    };
  }, [runId]);

  if (error) {
    return (
      <p className="form-error" role="alert" data-testid="compare-error">
        {error}
      </p>
    );
  }
  if (detail === null) {
    return (
      <p className="card__hint" data-testid="compare-loading">
        Comparing with {baselineName}…
      </p>
    );
  }

  if (!detail.comparable) {
    return (
      <div data-testid="compare-block">
        <h3>Compare with baseline</h3>
        <p className="card__hint" data-testid="compare-not-comparable">
          These runs cannot be compared, so no deltas are shown:
        </p>
        <ul data-testid="compare-reasons">
          {detail.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      </div>
    );
  }

  const classification = detail.classification ?? "unchanged";
  const flipped = detail.cases.pass_to_fail;
  const unmeasured = detail.metrics.filter((metric) => metric.status === "not measured");

  return (
    <div data-testid="compare-block">
      <h3>Compare with baseline</h3>
      <p>
        <span
          className={`badge ${classification === "regressed" ? "badge--no-go" : "badge--neutral"}`}
          data-testid={CLASS_TESTID[classification] ?? "compare-classification"}
        >
          {CLASS_LABEL[classification] ?? classification}
        </span>{" "}
        <span data-testid="compare-classification-reason">{detail.classification_reason}</span>
      </p>
      <p className="card__hint" data-testid="compare-existing-status">
        Stored comparison: {detail.existing_status} · tolerance {detail.tolerance.toFixed(2)}
      </p>

      <p data-testid="compare-verdict">
        Verdict: {detail.verdict.baseline ?? "—"} → {detail.verdict.current ?? "—"} (
        {detail.verdict.direction})
      </p>
      <p data-testid="compare-score">
        Weighted score: {detail.score.baseline === null ? "—" : detail.score.baseline.toFixed(2)} →{" "}
        {detail.score.current === null ? "—" : detail.score.current.toFixed(2)} (
        {signed(detail.score.delta)})
      </p>

      {detail.metrics.length > 0 ? (
        <table className="results__table" data-testid="compare-metrics">
          <thead>
            <tr>
              <th scope="col">Metric</th>
              <th scope="col">Baseline</th>
              <th scope="col">Now</th>
              <th scope="col">Delta</th>
            </tr>
          </thead>
          <tbody>
            {detail.metrics.map((metric) => (
              <tr key={metric.name}>
                <td>
                  {metric.name.replaceAll("_", " ")}
                  {metric.hard_gate ? " (hard gate)" : ""}
                </td>
                <td>{metric.status === "not measured" ? "not measured" : (metric.baseline ?? 0).toFixed(2)}</td>
                <td>{metric.status === "not measured" ? "not measured" : (metric.current ?? 0).toFixed(2)}</td>
                <td>{metric.status === "not measured" ? "not measured" : signed(metric.delta)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}

      {unmeasured.length > 0 ? (
        <p className="card__hint" data-testid="compare-unmeasured">
          Not measured on both sides, so no delta is shown:{" "}
          {unmeasured.map((metric) => metric.name.replaceAll("_", " ")).join(", ")}.
        </p>
      ) : null}

      {detail.hard_gates.newly_failed.length > 0 || detail.hard_gates.newly_passed.length > 0 ? (
        <div data-testid="compare-hard-gates">
          {detail.hard_gates.newly_failed.length > 0 ? (
            <p>Hard gates newly failed: {detail.hard_gates.newly_failed.join(", ")}</p>
          ) : null}
          {detail.hard_gates.newly_passed.length > 0 ? (
            <p>Hard gates newly passed: {detail.hard_gates.newly_passed.join(", ")}</p>
          ) : null}
        </div>
      ) : null}

      {flipped.length > 0 ? (
        <div data-testid="compare-flips">
          <p className="card__hint">
            Cases that passed before and fail now ({flipped.length}):
          </p>
          <ul>
            {flipped.map((item) => (
              <li key={item.row_index} data-testid={`compare-flip-${item.row_index}`}>
                <Link to={`/results?run=${detail.current_run_id}`} title={`Row ${item.row_index}`}>
                  {shortQuestion(item.input)}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {detail.noise_caution ? (
        <p className="card__hint" data-testid="compare-noise">
          {detail.noise_caution}
        </p>
      ) : null}
    </div>
  );
}
