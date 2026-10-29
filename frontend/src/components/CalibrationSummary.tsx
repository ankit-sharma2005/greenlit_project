import { useEffect, useState } from "react";

import { ApiError } from "../lib/api";
import { getCalibration, type CalibrationSummary as Summary } from "../lib/labels";
import "../styles/results.css";

export interface CalibrationSummaryProps {
  /** Bump this to re-read the summary after a label is saved. */
  refreshKey?: number;
}

function format(value: number | null, suffix = ""): string {
  return value === null ? "—" : `${value.toFixed(2)}${suffix}`;
}

/**
 * Raw agreement and Cohen's kappa between the judge and the human labels (M7).
 *
 * Kappa rather than raw agreement alone: on a lopsided set an always-"pass"
 * judge looks accurate, and kappa is what removes that flattery.
 */
export function CalibrationSummary({ refreshKey = 0 }: CalibrationSummaryProps) {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getCalibration()
      .then((value) => {
        if (active) {
          setSummary(value);
          setError(null);
        }
      })
      .catch((caught: unknown) => {
        if (!active) return;
        setSummary(null);
        setError(
          caught instanceof ApiError
            ? caught.message
            : "Could not read the calibration. Check that the API is running.",
        );
      });
    return () => {
      active = false;
    };
  }, [refreshKey]);

  if (error) {
    return (
      <p className="form-error" role="alert" data-testid="calibration-error">
        {error}
      </p>
    );
  }

  if (summary === null) {
    return (
      <p className="card__hint" data-testid="calibration-loading">
        Reading the calibration…
      </p>
    );
  }

  if (summary.labelled === 0) {
    return (
      <p className="card__hint" data-testid="calibration-empty">
        No labelled cases yet. Approve or reject a case above, and its label appears here.
      </p>
    );
  }

  return (
    <div data-testid="calibration-summary">
      <div className="verdict">
        <div>
          <span className="verdict__label">Labelled cases</span>
          <span className="verdict__score" data-testid="calibration-labelled">
            {summary.labelled}
          </span>
        </div>
        <div>
          <span className="verdict__label">Raw agreement</span>
          <span data-testid="calibration-agreement">{format(summary.raw_agreement)}</span>
        </div>
        <div>
          <span className="verdict__label">Cohen&apos;s kappa</span>
          <span data-testid="calibration-kappa">{format(summary.kappa)}</span>
        </div>
      </div>
      <p className="verdict__reason" data-testid="calibration-reading">
        {summary.reading}
      </p>
    </div>
  );
}
