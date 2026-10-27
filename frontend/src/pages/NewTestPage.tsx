import { useCallback, useEffect, useState } from "react";

import { Button } from "../components/Button";
import { DemoPanel } from "../components/DemoPanel";
import { PromptAppPanel } from "../components/PromptAppPanel";
import { RunProgressPanel } from "../components/RunProgressPanel";
import { Spinner } from "../components/Spinner";
import { parseCurl } from "../lib/curl";
import { testConnection } from "../lib/connectors";
import { ApiError } from "../lib/api";
import { listDatasets } from "../lib/datasets";
import { listProviders } from "../lib/providers";
import {
  cancelRun,
  getRun,
  isTerminal,
  quickTest,
  startRun,
  type Run,
  type RunCreateRequest,
  type TestType,
} from "../lib/runs";

type EntryPoint = "http_endpoint" | "prompt_app" | "upload_outputs";

interface TestTypes {
  quality: boolean;
  safety: boolean;
  operations: boolean;
}

interface DatasetOption {
  value: string;
  label: string;
}

interface ProviderOption {
  id: string;
  name: string;
  modelName: string;
}

const POLL_INTERVAL_MS = 1500;
const GENERATED_CASES = 10;

/** The checked test types, in a stable order. */
function chosenTestTypes(types: TestTypes): TestType[] {
  const chosen: TestType[] = [];
  if (types.quality) chosen.push("quality");
  if (types.safety) chosen.push("safety");
  if (types.operations) chosen.push("operations");
  return chosen;
}

/** Home: one page where a first-time user points GreenLit at an app and gets a verdict. */
export function NewTestPage() {
  const [connector, setConnector] = useState<EntryPoint>("http_endpoint");
  const [url, setUrl] = useState("");
  const [curlText, setCurlText] = useState("");
  const [showCurl, setShowCurl] = useState(false);
  const [curlNotice, setCurlNotice] = useState<string | null>(null);
  const [runsOnMyComputer, setRunsOnMyComputer] = useState(false);
  const [testTypes, setTestTypes] = useState<TestTypes>({
    quality: true,
    safety: true,
    operations: true,
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [datasetOptions, setDatasetOptions] = useState<DatasetOption[]>([]);
  const [datasetVersionId, setDatasetVersionId] = useState("");
  const [activeRun, setActiveRun] = useState<Run | null>(null);
  const [startingRun, setStartingRun] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [providerOptions, setProviderOptions] = useState<ProviderOption[]>([]);
  const [selectedProviderId, setSelectedProviderId] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [promptAppModel, setPromptAppModel] = useState("");
  const [promptDatasetId, setPromptDatasetId] = useState("");

  const [detectResult, setDetectResult] = useState<
    import("../lib/connectors").ConnectTestResponse | null
  >(null);
  const [answerPath, setAnswerPath] = useState<string>("");

  // Approved dataset versions are the only thing a run may execute.
  useEffect(() => {
    listDatasets()
      .then((response) => {
        const options: DatasetOption[] = [];
        for (const dataset of response.items) {
          for (const version of dataset.versions) {
            if (!version.approved_at) continue;
            options.push({
              value: version.id,
              label: `${dataset.name} · v${version.version_no} (${version.row_count} cases)`,
            });
          }
        }
        setDatasetOptions(options);
      })
      .catch(() => setDatasetOptions([]));
  }, []);

  // Active providers are the only ones a prompt-app run may use.
  useEffect(() => {
    listProviders()
      .then((providers) => {
        const active = providers.filter((provider) => provider.is_active);
        setProviderOptions(
          active.map((provider) => ({
            id: provider.id,
            name: provider.name,
            modelName: provider.model_name,
          })),
        );
        const first = active[0];
        if (first) {
          setSelectedProviderId((current) => current || first.id);
          setPromptAppModel((current) => current || first.model_name);
        }
      })
      .catch(() => setProviderOptions([]));
  }, []);

  // Poll the worker's counters until the run reaches a terminal state.
  const runId = activeRun?.id;
  const runState = activeRun?.state;
  useEffect(() => {
    if (!runId || !runState || isTerminal(runState)) return;
    let stopped = false;
    const timer = window.setInterval(() => {
      getRun(runId)
        .then((fresh) => {
          if (!stopped) setActiveRun(fresh);
        })
        .catch(() => {
          // Keep the last known state; the next tick tries again.
        });
    }, POLL_INTERVAL_MS);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [runId, runState]);

  const handleConnectorChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setConnector(e.target.value as EntryPoint);
    setUrl("");
    setCurlNotice(null);
    setError(null);
  };

  const toggleTestType = (key: keyof TestTypes) => {
    setTestTypes((previous) => ({ ...previous, [key]: !previous[key] }));
  };

  const applyCurl = () => {
    const parsed = parseCurl(curlText);
    if (!parsed) {
      setCurlNotice(
        "That does not look like a curl command with a URL. Paste the full command, starting with “curl”.",
      );
      return;
    }
    setUrl(parsed.url);
    setCurlNotice(
      `Parsed ${parsed.method} ${parsed.url}` +
        (parsed.headerCount > 0 ? ` with ${parsed.headerCount} header(s)` : "") +
        ". The request body will be mapped in a later step.",
    );
  };

  const handlePromptAppProviderChange = (providerId: string) => {
    setSelectedProviderId(providerId);
    const picked = providerOptions.find((option) => option.id === providerId);
    setPromptAppModel(picked ? picked.modelName : "");
  };

  const handleStartTest = async () => {
    setError(null);
    setNotice(null);
    setRunError(null);
    setDetectResult(null);
    const anyType = testTypes.quality || testTypes.safety || testTypes.operations;
    if (!anyType) {
      setError("Pick at least one test type — Quality, Safety or Operations.");
      return;
    }
    if (connector === "http_endpoint" && !url.trim()) {
      setError("Enter the URL of the app GreenLit should test (or paste a curl command).");
      return;
    }

    if (connector === "http_endpoint") {
      setLoading(true);
      try {
        const result = await testConnection({
          connector_type: "http_endpoint",
          url: url.trim(),
          method: "POST",
          auto_detect: true,
          allow_private_targets: runsOnMyComputer,
        });
        setDetectResult(result);
        setAnswerPath(result.detected_answer_path || "");
        setNotice("Auto-detect complete. These settings are used when the test runs.");
      } catch (caught) {
        if (caught instanceof ApiError) {
          setError(caught.message);
        } else {
          setError("Connection test failed.");
        }
      } finally {
        setLoading(false);
      }
      return;
    }

    if (connector === "prompt_app") {
      if (providerOptions.length === 0) {
        setError("Add a model provider in Settings → Providers, then start the test again.");
        return;
      }
      if (!selectedProviderId) {
        setError("Pick the provider this prompt app should answer with.");
        return;
      }
      const target = systemPrompt.trim();
      if (!target) {
        setError("Enter a system prompt so the model knows how to answer.");
        return;
      }
      setStartingRun(true);
      setActiveRun(null);
      try {
        if (promptDatasetId) {
          setActiveRun(
            await startRun({
              entry_point: "prompt_app",
              target,
              test_types: chosenTestTypes(testTypes),
              provider_id: selectedProviderId,
              model: promptAppModel.trim() || undefined,
              system_prompt: target,
              timeout_seconds: 60,
              allow_private_targets: runsOnMyComputer,
              dataset_version_id: promptDatasetId,
            }),
          );
          setNotice("Run queued. A worker executes the cases, this page polls its progress.");
        } else {
          const result = await quickTest({
            entry_point: "prompt_app",
            target,
            tests: chosenTestTypes(testTypes),
            provider_id: selectedProviderId,
            model: promptAppModel.trim() || undefined,
            timeout_seconds: 60,
            allow_private_targets: runsOnMyComputer,
            generate: GENERATED_CASES,
          });
          setActiveRun(result.run);
          setNotice(
            `GreenLit generated ${GENERATED_CASES} test cases, approved them and queued the run.`,
          );
        }
      } catch (caught) {
        setRunError(
          caught instanceof ApiError ? caught.message : "Could not start the test. Try again.",
        );
      } finally {
        setStartingRun(false);
      }
      return;
    }

    setNotice(
      "Uploaded-output runs already work through the API; this page gets their fields " +
        "in the next step. Datasets can be managed in Settings → Datasets.",
    );
  };

  const handleRunTest = useCallback(async () => {
    if (!detectResult) return;
    setRunError(null);
    setActiveRun(null);
    setStartingRun(true);
    const target = url.trim();
    const common: RunCreateRequest = {
      entry_point: "http_endpoint",
      target,
      test_types: chosenTestTypes(testTypes),
      method: "POST",
      body_template: detectResult.detected_request_shape || '{"question": {{input}}}',
      answer_path: answerPath || detectResult.detected_answer_path || undefined,
      context_path: detectResult.detected_context_path || undefined,
      timeout_seconds: 60,
      allow_private_targets: runsOnMyComputer,
    };
    try {
      if (datasetVersionId) {
        setActiveRun(await startRun({ ...common, dataset_version_id: datasetVersionId }));
        setNotice("Run queued. A worker executes the cases, this page polls its progress.");
      } else {
        // No dataset chosen: GreenLit writes the cases with the model first.
        const result = await quickTest({ ...common, target, generate: GENERATED_CASES });
        setActiveRun(result.run);
        setNotice(
          `GreenLit generated ${GENERATED_CASES} test cases, approved them and queued the run.`,
        );
      }
    } catch (caught) {
      setRunError(
        caught instanceof ApiError ? caught.message : "Could not start the test. Try again.",
      );
    } finally {
      setStartingRun(false);
    }
  }, [answerPath, datasetVersionId, detectResult, runsOnMyComputer, testTypes, url]);

  const handleCancelRun = async () => {
    if (!activeRun) return;
    setCancelling(true);
    setRunError(null);
    try {
      setActiveRun(await cancelRun(activeRun.id));
    } catch (caught) {
      setRunError(
        caught instanceof ApiError ? caught.message : "Could not cancel this run. Try again.",
      );
    } finally {
      setCancelling(false);
    }
  };

  return (
    <>
      <header className="page__header">
        <div>
          <h1>New Test</h1>
          <p className="page__description">
            Point GreenLit at your LLM app and get one decision — GO, REVIEW or NO-GO — with the
            evidence behind it.
          </p>
        </div>
      </header>

      <section className="card" aria-labelledby="target-heading">
        <div className="card__header">
          <h2 id="target-heading">What should GreenLit test?</h2>
          <p className="page__subtitle">Select how GreenLit should connect to your app.</p>
        </div>

        <p className="card__hint">
          Three entry points are available here: an HTTP endpoint, a prompt app (system prompt plus
          model), or uploaded outputs (CSV or JSON). Other entry points (Python function, Docker
          image, Git repository, CLI command, Proxy mode, Website URL, MCP server) are coming soon.
        </p>

        <div style={{ marginTop: "var(--space-5)" }}>
          <label className="form__label" htmlFor="connector-select">
            Entry point:
          </label>
          <select
            id="connector-select"
            data-testid="connector-select"
            value={connector}
            onChange={handleConnectorChange}
            disabled={loading}
          >
            <option value="http_endpoint">HTTP endpoint</option>
            <option value="prompt_app">Prompt app (system prompt + model)</option>
            <option value="upload_outputs">Upload outputs (CSV/JSON)</option>
            <optgroup label="Coming soon">
              <option disabled>Python function (traced)</option>
              <option disabled>Built-in RAG app</option>
              <option disabled>Python SDK (traced)</option>
              <option disabled>Docker image</option>
              <option disabled>Git repository</option>
              <option disabled>CLI command</option>
              <option disabled>Website URL</option>
              <option disabled>MCP server</option>
            </optgroup>
          </select>
        </div>

        {connector === "http_endpoint" && (
          <div style={{ marginTop: "var(--space-5)" }}>
            <label className="form__label" htmlFor="target-url">
              Target URL:
            </label>
            <input
              id="target-url"
              data-testid="target-url"
              type="text"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://myapp.local/ask"
              disabled={loading}
            />
            <button
              onClick={() => setShowCurl(!showCurl)}
              className="form__curl-button"
              type="button"
              disabled={loading}
              aria-expanded={showCurl}
            >
              {showCurl ? "Hide cURL" : "Paste cURL"}
            </button>

            {showCurl && (
              <div style={{ marginTop: "var(--space-3)" }}>
                <label className="form__label" htmlFor="curl-input">
                  Paste the full curl command:
                </label>
                <textarea
                  id="curl-input"
                  rows={3}
                  value={curlText}
                  onChange={(e) => setCurlText(e.target.value)}
                  placeholder={
                    'curl -X POST https://myapp.local/ask -H "Content-Type: application/json" -d \'{"question": "{{input}}"}\''
                  }
                  disabled={loading}
                />
                <div className="datasets__actions" style={{ marginTop: "var(--space-2)" }}>
                  <Button variant="secondary" onClick={applyCurl} disabled={loading}>
                    Use this request
                  </Button>
                </div>
                {curlNotice && (
                  <p className="form__hint" role="status">
                    {curlNotice}
                  </p>
                )}
              </div>
            )}
          </div>
        )}

        {connector === "prompt_app" && (
          <PromptAppPanel
            providerOptions={providerOptions}
            selectedProviderId={selectedProviderId}
            systemPrompt={systemPrompt}
            model={promptAppModel}
            datasetOptions={datasetOptions}
            datasetVersionId={promptDatasetId}
            generatedCases={GENERATED_CASES}
            disabled={startingRun}
            onProviderChange={handlePromptAppProviderChange}
            onSystemPromptChange={setSystemPrompt}
            onModelChange={setPromptAppModel}
            onDatasetChange={setPromptDatasetId}
          />
        )}

        {connector === "upload_outputs" && (
          <div style={{ marginTop: "var(--space-5)" }}>
            <label className="form__label">Upload file:</label>
            <input type="file" disabled={loading} />
            <p className="form__hint">
              CSV or JSON file with columns id, input, output (input and output required; the rest
              is auto-detected). This connects to the Datasets tab in Settings.
            </p>
          </div>
        )}

        <fieldset style={{ marginTop: "var(--space-5)" }}>
          <legend className="form__label">Test types (all on by default):</legend>
          <div className="datasets__actions">
            <label>
              <input
                type="checkbox"
                checked={testTypes.quality}
                onChange={() => toggleTestType("quality")}
                disabled={loading}
              />{" "}
              Quality
            </label>
            <label>
              <input
                type="checkbox"
                checked={testTypes.safety}
                onChange={() => toggleTestType("safety")}
                disabled={loading}
              />{" "}
              Safety
            </label>
            <label>
              <input
                type="checkbox"
                checked={testTypes.operations}
                onChange={() => toggleTestType("operations")}
                disabled={loading}
              />{" "}
              Operations (latency, errors, tokens)
            </label>
          </div>
          {testTypes.safety ? (
            <p className="form__hint">
              Safety scoring is recorded for the run; the built-in attack set arrives with M8.
            </p>
          ) : null}
        </fieldset>

        <div className="form__run-on-computer" style={{ marginTop: "var(--space-5)" }}>
          <input
            type="checkbox"
            id="runs-on-my-computer"
            checked={runsOnMyComputer}
            onChange={() => setRunsOnMyComputer(!runsOnMyComputer)}
            disabled={loading}
          />
          <label htmlFor="runs-on-my-computer">This app runs on my computer</label>
          <p className="form__hint">
            GreenLit reaches your local app through host.docker.internal when the API runs in
            Docker. Only enable this for targets you trust.
          </p>
        </div>

        {error && (
          <p className="form-error" role="alert" style={{ marginTop: "var(--space-4)" }}>
            {error}
          </p>
        )}

        {detectResult && (
          <div
            className="notice"
            role="status"
            data-testid="detect-result"
            style={{ marginTop: "var(--space-4)" }}
          >
            <strong>Detected</strong>
            <div style={{ marginTop: "var(--space-2)" }}>
              <div data-testid="detected-request-shape">
                Request body template:{" "}
                {detectResult.detected_request_shape || '{"question": {{input}}}'}
              </div>
              <div data-testid="detected-answer-path">
                Detected answer path:{" "}
                {detectResult.detected_answer_path || answerPath || "(auto-detected)"}
              </div>
              <div data-testid="detected-context-path">
                Detected context path: {detectResult.detected_context_path || "not instrumented"}
              </div>
              {detectResult.trace && (detectResult.trace as Record<string, unknown>).raw ? (
                <details style={{ marginTop: "var(--space-2)" }}>
                  <summary>Real response</summary>
                  <pre style={{ overflow: "auto", maxHeight: "200px" }}>
                    {JSON.stringify((detectResult.trace as Record<string, unknown>).raw, null, 2)}
                  </pre>
                </details>
              ) : null}
              <div style={{ marginTop: "var(--space-2)" }}>
                <label className="form__label" htmlFor="answer-path">
                  Correct answer path (one click):
                </label>
                <input
                  id="answer-path"
                  type="text"
                  data-testid="answer-path"
                  value={answerPath}
                  onChange={(e) => setAnswerPath(e.target.value)}
                  placeholder="choices.0.message.content"
                />
              </div>

              <div style={{ marginTop: "var(--space-4)" }}>
                <label className="form__label" htmlFor="run-dataset">
                  Test cases:
                </label>
                <select
                  id="run-dataset"
                  data-testid="run-dataset"
                  value={datasetVersionId}
                  onChange={(e) => setDatasetVersionId(e.target.value)}
                  disabled={startingRun}
                >
                  <option value="">
                    Generate {GENERATED_CASES} questions with your model provider
                  </option>
                  {datasetOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
                {datasetOptions.length === 0 ? (
                  <p className="form__hint">
                    No approved dataset yet. GreenLit writes the questions with your provider
                    (Settings → Providers), or upload a dataset in Settings → Datasets.
                  </p>
                ) : null}
              </div>

              <div className="datasets__actions" style={{ marginTop: "var(--space-3)" }}>
                <Button
                  variant="primary"
                  loading={startingRun}
                  onClick={() => void handleRunTest()}
                  disabled={startingRun}
                  data-testid="run-test"
                >
                  {startingRun ? <Spinner size="sm" label="Starting your test" /> : "Run test"}
                </Button>
              </div>
            </div>
          </div>
        )}

        <div style={{ marginTop: "var(--space-5)" }}>
          <Button
            variant="primary"
            size="lg"
            loading={loading}
            onClick={handleStartTest}
            data-testid="start-test"
          >
            {loading ? <Spinner size="sm" label="Checking your setup" /> : "Start test"}
          </Button>
        </div>

        {notice && !detectResult && (
          <div className="notice" role="status" style={{ marginTop: "var(--space-4)" }}>
            {notice}
          </div>
        )}

        {runError && (
          <p className="form-error" role="alert" style={{ marginTop: "var(--space-4)" }}>
            {runError}
          </p>
        )}

        {activeRun ? (
          <RunProgressPanel
            run={activeRun}
            onCancel={() => void handleCancelRun()}
            cancelling={cancelling}
          />
        ) : null}
      </section>

      <section
        className="card"
        aria-labelledby="demo-heading"
        style={{ marginTop: "var(--space-5)" }}
      >
        <div className="card__header">
          <h2 id="demo-heading">See it working first</h2>
        </div>
        <p className="card__hint">
          The demo runs a sample helpdesk app twice — a healthy version and a broken one — so you
          can see a GO and a NO-GO report without configuring anything.
        </p>
        <DemoPanel />
      </section>
    </>
  );
}
