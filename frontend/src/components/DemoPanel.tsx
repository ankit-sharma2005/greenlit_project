import { useEffect, useRef, useState } from "react";

import { Button } from "./Button";
import { RunProgressPanel } from "./RunProgressPanel";
import { Spinner } from "./Spinner";
import { ApiError } from "../lib/api";
import { loadDemo } from "../lib/demo";
import { getRun, isTerminal, startRun, type Run } from "../lib/runs";
import "../styles/results.css";

const POLL_INTERVAL_MS = 1500;
const DEMO_CASES_NOTE = "12 helpdesk cases, no model required";

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

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

/**
 * "Try the demo": one click runs the healthy demo app and the broken one over
 * the shipped golden dataset, then shows both verdicts side by side.
 *
 * The two runs go through the normal runs API, so this is the same code path as
 * a hand-made test; nothing here is precomputed.
 */
export function DemoPanel() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeRun, setActiveRun] = useState<Run | null>(null);
  const [results, setResults] = useState<Run[]>([]);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const handleTryDemo = async () => {
    setBusy(true);
    setError(null);
    setResults([]);
    setActiveRun(null);
    try {
      const setup = await loadDemo();
      const legs: Array<{ url: string; name: string }> = [
        { url: setup.good_url, name: "Demo — healthy helpdesk" },
        { url: setup.broken_url, name: "Demo — broken helpdesk" },
      ];
      for (const leg of legs) {
        let run = await startRun({
          name: leg.name,
          entry_point: "http_endpoint",
          target: leg.url,
          body_template: '{"question": {{input}}}',
          answer_path: "answer",
          context_path: "context",
          timeout_seconds: 60,
          allow_private_targets: true,
          dataset_version_id: setup.dataset_version_id,
        });
        setActiveRun(run);
        while (!isTerminal(run.state)) {
          await sleep(POLL_INTERVAL_MS);
          if (!mounted.current) return;
          run = await getRun(run.id);
          if (mounted.current) setActiveRun(run);
        }
        if (!mounted.current) return;
        setResults((previous) => [...previous, run]);
      }
      setActiveRun(null);
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "Could not start the demo. Check that the demo app is running and try again.",
      );
      setActiveRun(null);
    } finally {
      if (mounted.current) setBusy(false);
    }
  };

  const unreachable = results.length > 0 && results.every((run) => run.state === "failed");

  return (
    <div style={{ marginTop: "var(--space-5)" }}>
      <Button
        variant="secondary"
        onClick={() => void handleTryDemo()}
        loading={busy}
        disabled={busy}
        data-testid="try-demo"
      >
        {busy ? <Spinner size="sm" label="Running the demo" /> : "Try the demo"}
      </Button>
      <p className="form__hint" data-testid="demo-hint">
        Runs the shipped college-helpdesk dataset twice: a healthy app (expect GO) and a broken one
        (expect NO-GO, with the reason spelled out). {DEMO_CASES_NOTE}.
      </p>

      {error ? (
        <p className="form-error" role="alert" data-testid="demo-error">
          {error}
        </p>
      ) : null}

      {unreachable ? (
        <p className="form__hint" role="status" data-testid="demo-unreachable">
          The demo app did not answer. Start it with{" "}
          <code>docker compose --profile demo up -d</code>, then try again.
        </p>
      ) : null}

      {activeRun ? (
        <RunProgressPanel
          run={activeRun}
          onCancel={() => {
            /* the demo runs are short; the cancel button lives on New Test */
          }}
        />
      ) : null}

      {results.length > 0 ? (
        <>
          <h3 style={{ marginTop: "var(--space-5)" }} data-testid="demo-results">
            Demo results
          </h3>
          {results.map((run, index) => {
            const label = index === 0 ? "Healthy app" : "Broken app";
            const testid = index === 0 ? "demo-good" : "demo-broken";
            return (
              <section
                key={run.id}
                className="card"
                aria-label={label}
                data-testid={`${testid}-result`}
                style={{ marginTop: "var(--space-3)" }}
              >
                <div className="card__header">
                  <h4>{label}</h4>
                  <span className="badge">{run.name}</span>
                </div>
                <div className="verdict">
                  <span
                    className={`verdict__word ${VERDICT_CLASS[run.verdict ?? ""] ?? ""}`}
                    data-testid={`${testid}-verdict`}
                  >
                    {run.verdict ? (VERDICT_LABEL[run.verdict] ?? run.verdict) : "—"}
                  </span>
                  <div>
                    <span className="verdict__label">Weighted score</span>
                    <span className="verdict__score" data-testid={`${testid}-score`}>
                      {run.score === null ? "—" : run.score.toFixed(2)}
                    </span>
                  </div>
                  <div>
                    <span className="verdict__label">Cases</span>
                    <span>
                      {run.progress.items_done} of {run.progress.items_total}
                    </span>
                  </div>
                </div>
                <p className="verdict__reason" data-testid={`${testid}-reason`}>
                  {run.verdict_reason ?? run.state}
                </p>
              </section>
            );
          })}
        </>
      ) : null}
    </div>
  );
}
