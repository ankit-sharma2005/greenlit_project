import { useCallback, useEffect, useState } from "react";

import { Button } from "./Button";
import { ApiError } from "../lib/api";
import { clearBaseline, getBaseline, setBaseline, type Baseline } from "../lib/baselines";
import { getRun, type Run, type RunRegression } from "../lib/runs";
import "../styles/results.css";

const STATUS_LABEL: Record<string, string> = {
  PASS: "Pass",
  WARN: "Warn",
  BLOCK: "Block",
};

const STATUS_CLASS: Record<string, string> = {
  PASS: "results__state--pass",
  WARN: "results__state--skip",
  BLOCK: "results__state--fail",
};

export interface BaselinePanelProps {
  run: Run;
}

/**
 * The baseline of the run's dataset version, and how this run compares (spec 8.5).
 *
 * One baseline per dataset version: setting it here replaces the previous one,
 * and clearing it stops future comparisons. The comparison itself is stored by
 * the worker when a run finishes, so this panel only reads it — and re-reads the
 * run after a change so the numbers on screen match the baseline it names.
 */
export function BaselinePanel({ run }: BaselinePanelProps) {
  const [baseline, setBaselineValue] = useState<Baseline | null | undefined>(undefined);
  const [regression, setRegression] = useState<RunRegression | null>(run.regression ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const completed = run.state === "completed";

  useEffect(() => {
    if (!completed) return;
    let active = true;
    getBaseline(run.id)
      .then((value) => {
        if (active) setBaselineValue(value);
      })
      .catch(() => {
        // A failed lookup must not hide the card; the button still works.
        if (active) setBaselineValue(null);
      });
    return () => {
      active = false;
    };
  }, [completed, run.id]);

  const refresh = useCallback(async () => {
    const [freshBaseline, freshRun] = await Promise.all([getBaseline(run.id), getRun(run.id)]);
    setBaselineValue(freshBaseline);
    setRegression(freshRun.regression ?? null);
  }, [run.id]);

  const handleSet = async () => {
    setBusy(true);
    setError(null);
    try {
      await setBaseline(run.id);
      await refresh();
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "Could not set the baseline. Check that the run is finished and try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  const handleClear = async () => {
    setBusy(true);
    setError(null);
    try {
      await clearBaseline(run.id);
      await refresh();
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "Could not clear the baseline. Check that it still exists and try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  if (!completed) {
    return (
      <section
        className="card"
        data-testid="baseline-panel"
        style={{ marginTop: "var(--space-5)" }}
      >
        <div className="card__header">
          <h2>Baseline</h2>
        </div>
        <p className="card__hint">
          A finished run can become this dataset version&apos;s baseline, and later runs are
          compared with it.
        </p>
      </section>
    );
  }

  // Before the lookup answers, trust the run payload; after it, trust the server,
  // so clearing the baseline immediately stops calling this run the baseline.
  const isBaseline =
    baseline === undefined ? run.is_baseline === true : baseline?.run_id === run.id;

  return (
    <section className="card" data-testid="baseline-panel" style={{ marginTop: "var(--space-5)" }}>
      <div className="card__header">
        <h2>Regression</h2>
        {regression ? (
          <span className={STATUS_CLASS[regression.status] ?? ""} data-testid="regression-status">
            {STATUS_LABEL[regression.status] ?? regression.status}
          </span>
        ) : null}
      </div>

      {baseline === undefined ? (
        <p className="card__hint" data-testid="baseline-loading">
          Checking the baseline…
        </p>
      ) : isBaseline ? (
        <p className="card__hint" data-testid="baseline-is-self">
          This run is the baseline for this dataset version.
        </p>
      ) : baseline === null ? (
        <p className="card__hint" data-testid="baseline-none">
          No baseline is set for this dataset version, so there is nothing to compare. Set this run
          as the baseline to check later runs against it.
        </p>
      ) : (
        <p className="card__hint" data-testid="baseline-current">
          Baseline: <strong>{baseline.run_name ?? "another run"}</strong> (metric tolerance{" "}
          {baseline.metric_tolerance.toFixed(2)}, {baseline.case_tolerance} regressed cases
          allowed).
        </p>
      )}

      {error ? (
        <p className="form-error" role="alert" data-testid="baseline-error">
          {error}
        </p>
      ) : null}

      {regression ? (
        <>
          <p className="verdict__reason" data-testid="regression-reason">
            {regression.reason}
          </p>
          {regression.metric_deltas.length > 0 ? (
            <table className="results__table" data-testid="regression-metrics">
              <thead>
                <tr>
                  <th scope="col">Metric</th>
                  <th scope="col">Baseline</th>
                  <th scope="col">Now</th>
                  <th scope="col">Delta</th>
                </tr>
              </thead>
              <tbody>
                {regression.metric_deltas.map((metric) => (
                  <tr key={metric.name}>
                    <td>{metric.name.replaceAll("_", " ")}</td>
                    <td>{metric.baseline === null ? "—" : metric.baseline.toFixed(2)}</td>
                    <td>{metric.current === null ? "—" : metric.current.toFixed(2)}</td>
                    <td className={metric.regressed ? "results__state--fail" : undefined}>
                      {metric.delta === null
                        ? "—"
                        : `${metric.delta >= 0 ? "+" : ""}${metric.delta.toFixed(2)}`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
          {regression.regressed_cases.length > 0 ? (
            <div data-testid="regression-cases">
              <p className="card__hint">
                Cases that passed before and fail now ({regression.regressed_cases.length}):
              </p>
              <ul>
                {regression.regressed_cases.map((item) => (
                  <li key={item.row_index}>{item.input}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </>
      ) : null}

      <div style={{ marginTop: "var(--space-4)" }}>
        {baseline === null && !isBaseline ? (
          <Button
            variant="secondary"
            onClick={() => void handleSet()}
            loading={busy}
            disabled={busy}
            data-testid="baseline-set"
          >
            Set as baseline
          </Button>
        ) : null}
        {isBaseline || baseline ? (
          <Button
            variant="secondary"
            onClick={() => void handleClear()}
            loading={busy}
            disabled={busy}
            data-testid="baseline-clear"
          >
            Clear baseline
          </Button>
        ) : null}
      </div>
    </section>
  );
}
