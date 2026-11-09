import { useCallback, useEffect, useState } from "react";

import { Button } from "./Button";
import { DemoPanel } from "./DemoPanel";
import { RunProgressPanel } from "./RunProgressPanel";
import { RunTrend } from "./charts/RunTrend";
import { useCriteriaThresholds } from "./charts/useCriteriaThresholds";
import { Spinner } from "./Spinner";
import { ApiError } from "../lib/api";
import { INTERRUPTED_NOTE, cancelRun, getRun, isTerminal, listRuns, type Run } from "../lib/runs";
import type { MetricRow } from "../lib/evaluations";
import "../styles/results.css";

const VERDICT_LABEL: Record<string, string> = {
  GO: "Go",
  REVIEW: "Review",
  NO_GO: "No-Go",
};

const VERDICT_CLASS: Record<string, string> = {
  GO: "verdict__word--go",
  REVIEW: "verdict__word--review",
  NO_GO: "verdict__word--no-go",
};

const STATE_LABEL: Record<string, string> = {
  queued: "Queued",
  running: "Running",
  cancelling: "Cancelling",
  cancelled: "Cancelled",
  failed: "Failed",
  completed: "Completed",
  stopped_by_limit: "Stopped by limit",
  interrupted: "Interrupted",
};

function scoreOf(metric: MetricRow | undefined): string {
  if (!metric || !metric.instrumented) return "—";
  return metric.score.toFixed(2);
}

/**
 * Run history for the Results page: the user's runs, the stored verdict, and a
 * side-by-side compare of two runs.
 */
export function RunHistory() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [openRunId, setOpenRunId] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [compareRuns, setCompareRuns] = useState<[Run, Run] | null>(null);
  const [openRun, setOpenRun] = useState<Run | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const trendThresholds = useCriteriaThresholds();

  const load = useCallback(async () => {
    try {
      const response = await listRuns({ limit: 50 });
      setRuns(response.items);
      setError(null);
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : "Could not load your runs. Try again.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Keep an open run live until it reaches a terminal state.
  useEffect(() => {
    if (!openRun || isTerminal(openRun.state)) return;
    const timer = window.setInterval(() => {
      getRun(openRun.id)
        .then(setOpenRun)
        .catch(() => {
          /* keep the last known state; the next tick retries */
        });
    }, 1500);
    return () => window.clearInterval(timer);
  }, [openRun]);

  const handleCancel = async () => {
    if (!openRun) return;
    setCancelling(true);
    setError(null);
    try {
      setOpenRun(await cancelRun(openRun.id));
      await load();
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : "Could not cancel this run. Try again.",
      );
    } finally {
      setCancelling(false);
    }
  };

  const handleOpen = async (run: Run) => {
    setOpenRunId(run.id);
    setOpenRun(run);
    setError(null);
    try {
      setOpenRun(await getRun(run.id));
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "Could not load this run’s full results. Try again.",
      );
    }
  };

  const toggleSelected = (runId: string) => {
    setCompareRuns(null);
    setSelectedIds((current) => {
      if (current.includes(runId)) return current.filter((id) => id !== runId);
      if (current.length >= 2) return [current[1] as string, runId];
      return [...current, runId];
    });
  };

  const handleCompare = async () => {
    if (selectedIds.length !== 2) return;
    try {
      const [first, second] = await Promise.all(selectedIds.map((id) => getRun(id)));
      if (!first || !second) return;
      setCompareRuns([first, second]);
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : "Could not load the two runs to compare.",
      );
    }
  };

  if (loading) {
    return (
      <section className="card" aria-labelledby="run-history-heading">
        <div className="card__header">
          <h2 id="run-history-heading">Your runs</h2>
        </div>
        <Spinner label="Loading your runs" />
      </section>
    );
  }

  return (
    <>
      <section
        className="card"
        aria-labelledby="run-history-heading"
        data-testid="run-history"
        style={{ marginTop: "var(--space-5)" }}
      >
        <div className="card__header">
          <h2 id="run-history-heading">Your runs</h2>
          <span className="badge" data-testid="run-history-count">
            {runs.length}
          </span>
        </div>

        <p className="card__hint">
          Every run GreenLit executed, newest first. Open one to see its verdict, or pick two to
          compare them metric by metric.
        </p>

        {error ? (
          <p className="form-error" role="alert" data-testid="run-history-error">
            {error}
          </p>
        ) : null}

        {runs.length === 0 ? (
          <div className="empty-state" data-testid="run-history-empty">
            <h3>No runs yet</h3>
            <p>Start a test from the New Test page and its verdict will show up here.</p>
            <DemoPanel />
          </div>
        ) : (
          <table className="results__table" data-testid="run-history-table">
            <thead>
              <tr>
                <th scope="col">Compare</th>
                <th scope="col">Run</th>
                <th scope="col">State</th>
                <th scope="col">Verdict</th>
                <th scope="col">Score</th>
                <th scope="col"> </th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.id} data-testid="run-history-row">
                  <td>
                    <input
                      type="checkbox"
                      aria-label={`Select ${run.name} to compare`}
                      data-testid="run-history-select"
                      checked={selectedIds.includes(run.id)}
                      onChange={() => toggleSelected(run.id)}
                    />
                  </td>
                  <td>{run.name}</td>
                  <td>
                    <span
                      className={`badge${run.state === "interrupted" ? " badge--interrupted" : ""}`}
                      data-testid="run-history-state"
                    >
                      {STATE_LABEL[run.state] ?? run.state}
                      {run.is_partial ? " · partial" : ""}
                    </span>
                    {run.state === "interrupted" ? (
                      <p className="card__hint" data-testid="run-history-interrupted-note">
                        {INTERRUPTED_NOTE}
                      </p>
                    ) : null}
                  </td>
                  <td>
                    {run.verdict ? (
                      <span
                        className={`verdict__word ${VERDICT_CLASS[run.verdict] ?? ""}`}
                        data-testid="run-history-verdict"
                      >
                        {VERDICT_LABEL[run.verdict] ?? run.verdict}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td data-testid="run-history-score">
                    {run.score === null ? "—" : run.score.toFixed(2)}
                  </td>
                  <td>
                    <Button
                      variant="secondary"
                      onClick={() => void handleOpen(run)}
                      data-testid="run-history-open"
                    >
                      {openRunId === run.id ? "Open" : "View verdict"}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <div className="datasets__actions" style={{ marginTop: "var(--space-3)" }}>
          <Button
            variant="primary"
            onClick={() => void handleCompare()}
            disabled={selectedIds.length !== 2}
            data-testid="run-history-compare"
          >
            Compare {selectedIds.length === 2 ? "these two" : selectedIds.length + " of 2"}
          </Button>
          {selectedIds.length === 2 ? (
            <Button
              variant="secondary"
              onClick={() => setSelectedIds([])}
              data-testid="run-history-clear"
            >
              Clear selection
            </Button>
          ) : null}
        </div>
      </section>

      {compareRuns ? <RunCompare runs={compareRuns} /> : null}

      <RunTrend runs={runs} thresholds={trendThresholds} />

      {openRun ? (
        <>
          <section className="card" style={{ marginTop: "var(--space-5)" }}>
            <div className="card__header">
              <h3 data-testid="run-detail-heading">{openRun.name}</h3>
              <Button
                variant="ghost"
                onClick={() => setOpenRun(null)}
                data-testid="run-detail-close"
              >
                Close
              </Button>
            </div>
          </section>
          <RunProgressPanel
            run={openRun}
            onCancel={() => void handleCancel()}
            cancelling={cancelling}
          />
        </>
      ) : null}
    </>
  );
}

/** Two runs side by side: every metric of either run, with the delta. */
function RunCompare({ runs }: { runs: [Run, Run] }) {
  const [baseline, candidate] = runs;
  const names = [...new Set([...baseline.metrics, ...candidate.metrics].map((m) => m.name))].sort();

  return (
    <section
      className="card"
      aria-labelledby="compare-heading"
      data-testid="run-compare"
      style={{ marginTop: "var(--space-5)" }}
    >
      <div className="card__header">
        <h2 id="compare-heading">Compare two runs</h2>
        <span className="badge">
          {baseline.name} vs {candidate.name}
        </span>
      </div>

      <table className="results__table" data-testid="run-compare-table">
        <thead>
          <tr>
            <th scope="col">Metric</th>
            <th scope="col">{baseline.name}</th>
            <th scope="col">{candidate.name}</th>
            <th scope="col">Change</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Verdict</td>
            <td data-testid="compare-baseline-verdict">
              {VERDICT_LABEL[baseline.verdict ?? ""] ?? baseline.verdict ?? "—"}
            </td>
            <td data-testid="compare-candidate-verdict">
              {VERDICT_LABEL[candidate.verdict ?? ""] ?? candidate.verdict ?? "—"}
            </td>
            <td>
              {(baseline.verdict ?? "") === (candidate.verdict ?? "") ? "unchanged" : "changed"}
            </td>
          </tr>
          <tr>
            <td>Weighted score</td>
            <td data-testid="compare-baseline-score">
              {baseline.score === null ? "—" : baseline.score.toFixed(2)}
            </td>
            <td data-testid="compare-candidate-score">
              {candidate.score === null ? "—" : candidate.score.toFixed(2)}
            </td>
            <td data-testid="compare-score-delta">
              {baseline.score === null || candidate.score === null
                ? "—"
                : `${candidate.score - baseline.score >= 0 ? "+" : ""}${(candidate.score - baseline.score).toFixed(2)}`}
            </td>
          </tr>
          {names.map((name) => {
            const before = baseline.metrics.find((metric) => metric.name === name);
            const after = candidate.metrics.find((metric) => metric.name === name);
            const comparable = before?.instrumented === true && after?.instrumented === true;
            const delta = comparable && before && after ? after.score - before.score : null;
            const change = !comparable
              ? "not instrumented"
              : delta === null
                ? "—"
                : Math.abs(delta) < 1e-9
                  ? "unchanged"
                  : delta > 0
                    ? "improved"
                    : "regressed";
            return (
              <tr key={name} data-testid="run-compare-row">
                <td>{name.replaceAll("_", " ")}</td>
                <td data-testid="compare-baseline-metric">{scoreOf(before)}</td>
                <td data-testid="compare-candidate-metric">{scoreOf(after)}</td>
                <td data-testid="compare-change">{change}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
