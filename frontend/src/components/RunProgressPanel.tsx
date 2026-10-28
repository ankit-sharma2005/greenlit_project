import { Button } from "./Button";
import { ProgressBar } from "./ProgressBar";
import { SafetySection } from "./SafetySection";
import { Spinner } from "./Spinner";
import { isTerminal, type Run } from "../lib/runs";
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
};

export interface RunProgressPanelProps {
  run: Run;
  onCancel: () => void;
  cancelling?: boolean;
}

/** Live progress while the worker runs, then the verdict with its evidence. */
export function RunProgressPanel({ run, onCancel, cancelling = false }: RunProgressPanelProps) {
  const active = !isTerminal(run.state);
  const total = run.progress.items_total;
  const done = run.progress.items_done;

  return (
    <>
      <section
        className="card"
        aria-labelledby="run-progress-heading"
        data-testid="run-progress"
        style={{ marginTop: "var(--space-5)" }}
      >
        <div className="card__header">
          <h2 id="run-progress-heading">Your test</h2>
          <span className="badge" data-testid="run-state">
            {STATE_LABEL[run.state] ?? run.state}
            {run.is_partial ? " · partial results" : ""}
          </span>
        </div>

        <ProgressBar
          value={done}
          max={Math.max(total, 1)}
          label={active ? `Running: ${run.progress.stage}` : `Finished: ${run.progress.stage}`}
        />

        <p className="card__hint" data-testid="run-counters">
          {done} of {Math.max(total, done)} cases done
          {run.progress.items_failed > 0 ? ` · ${run.progress.items_failed} failed` : ""}
          {run.progress.items_cancelled > 0 ? ` · ${run.progress.items_cancelled} cancelled` : ""}
          {run.progress.elapsed_seconds !== null
            ? ` · ${run.progress.elapsed_seconds.toFixed(0)} s elapsed`
            : ""}
        </p>

        {active ? (
          <div className="datasets__actions" style={{ marginTop: "var(--space-3)" }}>
            <Spinner size="sm" label="Worker is running your cases" />
            <Button
              variant="secondary"
              onClick={onCancel}
              loading={cancelling}
              disabled={run.state === "cancelling"}
              data-testid="cancel-run"
            >
              Cancel
            </Button>
          </div>
        ) : null}
      </section>

      {isTerminal(run.state) && run.verdict ? <RunVerdict run={run} /> : null}

      {isTerminal(run.state) && !run.verdict && run.verdict_reason ? (
        <section className="card" data-testid="run-verdict" style={{ marginTop: "var(--space-5)" }}>
          <div className="card__header">
            <h2>No verdict</h2>
          </div>
          <p className="verdict__reason" data-testid="run-verdict-reason">
            {run.verdict_reason}
          </p>
        </section>
      ) : null}
    </>
  );
}

function RunVerdict({ run }: { run: Run }) {
  return (
    <>
      <section
        className="card"
        aria-labelledby="run-verdict-heading"
        data-testid="run-verdict"
        style={{ marginTop: "var(--space-5)" }}
      >
        <div className="card__header">
          <h2 id="run-verdict-heading">Verdict</h2>
          <span className="badge">
            {run.name}
            {run.is_partial ? " · partial" : ""}
          </span>
        </div>

        <div className="verdict">
          <span
            className={`verdict__word ${VERDICT_CLASS[run.verdict ?? ""] ?? ""}`}
            data-testid="run-verdict-word"
          >
            {VERDICT_LABEL[run.verdict ?? ""] ?? run.verdict}
          </span>
          <div>
            <span className="verdict__label">Weighted score</span>
            <span className="verdict__score" data-testid="run-verdict-score">
              {run.score === null ? "—" : run.score.toFixed(2)}
            </span>
          </div>
          <div>
            <span className="verdict__label">Criteria</span>
            <span>{run.criteria_profile.replaceAll("_", " ")}</span>
          </div>
          <div>
            <span className="verdict__label">Cases</span>
            <span>
              {run.progress.items_done} of {run.progress.items_total}
            </span>
          </div>
          <div>
            <span className="verdict__label">Judge</span>
            <span data-testid="run-verdict-judge">
              {run.judge
                ? `${run.judge.model ?? "unknown model"} · rubric ${run.judge.rubric_version ?? "—"}`
                : "not used"}
            </span>
          </div>
        </div>

        <p className="verdict__reason" data-testid="run-verdict-reason">
          {run.verdict_reason}
        </p>

        {run.judge ? (
          run.judge.unavailable_items > 0 || run.judge.low_confidence_items > 0 ? (
            <p className="card__hint" data-testid="run-verdict-judge-note">
              {run.judge.unavailable_items > 0
                ? `The judge could not score ${run.judge.unavailable_items} answer(s).`
                : ""}
              {run.judge.unavailable_items > 0 && run.judge.low_confidence_items > 0 ? " " : ""}
              {run.judge.low_confidence_items > 0
                ? `It was unsure about ${run.judge.low_confidence_items} answer(s).`
                : ""}
            </p>
          ) : null
        ) : (
          <p className="card__hint" data-testid="run-verdict-judge-skipped">
            Judge skipped: {run.judge_skipped_reason ?? "no judge was configured for this run."}
          </p>
        )}
      </section>

      <SafetySection metrics={run.metrics} />

      {run.metrics.length > 0 ? (
        <section className="card" style={{ marginTop: "var(--space-5)" }}>
          <div className="card__header">
            <h2>Metrics</h2>
          </div>
          <table className="results__table" data-testid="run-metrics">
            <thead>
              <tr>
                <th scope="col">Metric</th>
                <th scope="col">Score</th>
                <th scope="col">State</th>
                <th scope="col">Weight</th>
                <th scope="col">Why</th>
              </tr>
            </thead>
            <tbody>
              {run.metrics.map((metric) => (
                <tr key={metric.name}>
                  <td>{metric.name.replaceAll("_", " ")}</td>
                  <td className="results__metric-score">
                    {metric.instrumented ? metric.score.toFixed(2) : "—"}
                  </td>
                  <td>
                    {metric.instrumented ? (
                      <span
                        className={metric.passed ? "results__state--pass" : "results__state--fail"}
                      >
                        {metric.passed ? "pass" : "fail"}
                      </span>
                    ) : (
                      <span className="results__state--skip">not instrumented</span>
                    )}
                  </td>
                  <td>{metric.weight.toFixed(2)}</td>
                  <td>{metric.explanation}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}

      {run.failed_cases.length > 0 ? (
        <section className="card" style={{ marginTop: "var(--space-5)" }}>
          <div className="card__header">
            <h2>Cases that failed</h2>
            <span className="badge">{run.failed_cases.length}</span>
          </div>
          <table className="results__table" data-testid="run-failed-cases">
            <thead>
              <tr>
                <th scope="col">Input</th>
                <th scope="col">Actual</th>
                <th scope="col">Reason</th>
              </tr>
            </thead>
            <tbody>
              {run.failed_cases.map((failure) => (
                <tr key={`${failure.input}-${failure.reason}`}>
                  <td>{failure.input}</td>
                  <td>{failure.actual || "—"}</td>
                  <td>{failure.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}
    </>
  );
}
