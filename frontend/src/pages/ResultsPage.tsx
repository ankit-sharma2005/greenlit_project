import { useCallback, useEffect, useState } from "react";

import { Button } from "../components/Button";
import { RunHistory } from "../components/RunHistory";
import { Spinner } from "../components/Spinner";
import { ApiError } from "../lib/api";
import {
  SAMPLE_OUTPUTS,
  listTemplates,
  previewEvaluation,
  type CriteriaTemplate,
  type PreviewResponse,
} from "../lib/evaluations";
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

function shortMetric(name: string): string {
  return name.replaceAll("_", " ");
}

/** Results: score a set of outputs and show the verdict, evidence and failed cases. */
export function ResultsPage() {
  const [templates, setTemplates] = useState<CriteriaTemplate[]>([]);
  const [profile, setProfile] = useState("rag_chatbot");
  const [csv, setCsv] = useState("");
  const [result, setResult] = useState<PreviewResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listTemplates()
      .then((response) => {
        setTemplates(response.templates);
        setProfile(response.default);
      })
      .catch(() => setTemplates([]));
  }, []);

  const handleEvaluate = useCallback(async () => {
    setError(null);
    if (!csv.trim()) {
      setError("Paste the app's outputs first, or load the example.");
      return;
    }
    setLoading(true);
    try {
      setResult(await previewEvaluation({ profile, csv }));
    } catch (caught) {
      setResult(null);
      setError(
        caught instanceof ApiError
          ? caught.message
          : "Could not evaluate these outputs. Check the columns and try again.",
      );
    } finally {
      setLoading(false);
    }
  }, [csv, profile]);

  const activeTemplate = templates.find((template) => template.key === profile);

  return (
    <>
      <header className="page__header">
        <div>
          <h1>Results</h1>
          <p className="page__description">
            Every run's verdict with its evidence, compare two runs side by side, or score a set of
            outputs directly.
          </p>
        </div>
      </header>

      <RunHistory />

      <section className="card" aria-labelledby="evaluate-heading" style={{ marginTop: "var(--space-5)" }}>
        <div className="card__header">
          <h2 id="evaluate-heading">Evaluate outputs</h2>
        </div>
        <p className="card__hint">
          A CSV with <code>input</code> and <code>output</code> columns is enough. Add{" "}
          <code>expected_answer</code>, <code>retrieved_context</code>,{" "}
          <code>reference_context</code>, <code>latency_ms</code> and token columns to measure more.
          Missing columns are reported as “not instrumented” and never counted as zero.
        </p>

        <div style={{ marginTop: "var(--space-4)" }}>
          <label className="form__label" htmlFor="criteria-profile">
            Criteria profile:
          </label>
          <select
            id="criteria-profile"
            data-testid="criteria-profile"
            value={profile}
            onChange={(event) => setProfile(event.target.value)}
            disabled={loading}
          >
            {templates.map((template) => (
              <option key={template.key} value={template.key}>
                {template.name}
              </option>
            ))}
          </select>
          {activeTemplate ? <p className="card__hint">{activeTemplate.description}</p> : null}
        </div>

        <div style={{ marginTop: "var(--space-4)" }}>
          <label className="form__label" htmlFor="outputs-csv">
            Outputs (CSV):
          </label>
          <textarea
            id="outputs-csv"
            data-testid="outputs-csv"
            className="results__textarea form__textarea"
            rows={8}
            value={csv}
            onChange={(event) => setCsv(event.target.value)}
            placeholder="input,expected_answer,output,latency_ms"
            disabled={loading}
          />
          <div className="results__toolbar">
            <Button
              type="button"
              variant="secondary"
              onClick={() => setCsv(SAMPLE_OUTPUTS.good)}
              disabled={loading}
            >
              Load good example
            </Button>
            <Button
              type="button"
              variant="secondary"
              onClick={() => setCsv(SAMPLE_OUTPUTS.broken)}
              disabled={loading}
            >
              Load broken example
            </Button>
            <Button
              type="button"
              variant="primary"
              loading={loading}
              onClick={() => void handleEvaluate()}
              data-testid="evaluate-button"
            >
              {loading ? <Spinner size="sm" label="Scoring outputs" /> : "Evaluate"}
            </Button>
          </div>
        </div>

        {error ? (
          <p className="form-error" role="alert" style={{ marginTop: "var(--space-4)" }}>
            {error}
          </p>
        ) : null}
      </section>

      {result ? <VerdictReport result={result} /> : null}

      {!result && !loading ? (
        <section className="empty-state" style={{ marginTop: "var(--space-5)" }}>
          <h2>No verdict yet</h2>
          <p>
            Load an example or paste your own outputs, then press Evaluate. Runs started from the
            New Test page show their verdict there, scored by the same engine.
          </p>
        </section>
      ) : null}
    </>
  );
}

function VerdictReport({ result }: { result: PreviewResponse }) {
  const p50 = result.metrics.find((metric) => metric.name === "latency_under_limit")?.details
    ?.p50_ms as number | undefined;
  const p95 = result.metrics.find((metric) => metric.name === "latency_under_limit")?.details
    ?.p95_ms as number | undefined;

  return (
    <>
      <section
        className="card"
        aria-labelledby="verdict-heading"
        data-testid="verdict-card"
        style={{ marginTop: "var(--space-5)" }}
      >
        <div className="card__header">
          <h2 id="verdict-heading">Verdict</h2>
          <span className="badge">
            {result.profile_name} · {result.item_count} cases
          </span>
        </div>

        <div className="verdict">
          <span
            className={`verdict__word ${VERDICT_CLASS[result.verdict] ?? ""}`}
            data-testid="verdict-word"
          >
            {VERDICT_LABEL[result.verdict] ?? result.verdict}
          </span>
          <div>
            <span className="verdict__label">Weighted score</span>
            <span className="verdict__score" data-testid="verdict-score">
              {result.score === null ? "—" : result.score.toFixed(2)}
            </span>
          </div>
          <div>
            <span className="verdict__label">Thresholds</span>
            <span data-testid="verdict-thresholds">
              REVIEW {result.review_threshold.toFixed(2)} · GO {result.go_threshold.toFixed(2)}
            </span>
          </div>
          <div>
            <span className="verdict__label">Valid cases</span>
            <span>
              {result.valid_items} of {result.item_count}
            </span>
          </div>
          {p50 !== undefined && p95 !== undefined ? (
            <div>
              <span className="verdict__label">Latency</span>
              <span>
                p50 {Math.round(p50)} ms · p95 {Math.round(p95)} ms
              </span>
            </div>
          ) : null}
        </div>

        <p className="verdict__reason" data-testid="verdict-reason">
          {result.reason}
        </p>

        {result.suggested_fixes.length > 0 ? (
          <>
            <h3 style={{ marginTop: "var(--space-4)" }}>Suggested fixes</h3>
            <ul className="verdict__fixes" data-testid="suggested-fixes">
              {result.suggested_fixes.map((fix) => (
                <li key={fix}>{fix}</li>
              ))}
            </ul>
          </>
        ) : null}
      </section>

      <section
        className="card"
        aria-labelledby="metrics-heading"
        style={{ marginTop: "var(--space-5)" }}
      >
        <div className="card__header">
          <h2 id="metrics-heading">Metrics</h2>
        </div>
        <table className="results__table" data-testid="metrics-table">
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
            {result.metrics.map((metric) => (
              <tr key={metric.name}>
                <td>{shortMetric(metric.name)}</td>
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

      <section
        className="card"
        aria-labelledby="failed-heading"
        style={{ marginTop: "var(--space-5)" }}
      >
        <div className="card__header">
          <h2 id="failed-heading">Failed cases</h2>
          <span className="badge">{result.failed_cases.length}</span>
        </div>
        {result.failed_cases.length === 0 ? (
          <p className="card__hint">No case failed. Every measured metric passed.</p>
        ) : (
          <table className="results__table" data-testid="failed-cases">
            <thead>
              <tr>
                <th scope="col">Input</th>
                <th scope="col">Expected</th>
                <th scope="col">Actual</th>
                <th scope="col">Reason</th>
              </tr>
            </thead>
            <tbody>
              {result.failed_cases.map((failure) => (
                <tr key={`${failure.input}-${failure.actual}`}>
                  <td>{failure.input}</td>
                  <td>{failure.expected || "—"}</td>
                  <td>{failure.actual}</td>
                  <td>{failure.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}
