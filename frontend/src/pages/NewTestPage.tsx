import { useState } from "react";

import { Button } from "../components/Button";
import { ComingSoon } from "../components/ComingSoon";
import { Spinner } from "../components/Spinner";
import { parseCurl } from "../lib/curl";

type EntryPoint = "http_endpoint" | "prompt_app" | "upload_outputs";

interface TestTypes {
  quality: boolean;
  safety: boolean;
  operations: boolean;
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

  const handleStartTest = () => {
    setError(null);
    const anyType = testTypes.quality || testTypes.safety || testTypes.operations;
    if (!anyType) {
      setError("Pick at least one test type — Quality, Safety or Operations.");
      return;
    }
    if (connector === "http_endpoint" && !url.trim()) {
      setError("Enter the URL of the app GreenLit should test (or paste a curl command).");
      return;
    }
    // The runs API (queued executions, progress, verdicts) ships in M6. Be honest about it.
    setLoading(true);
    window.setTimeout(() => {
      setLoading(false);
      setNotice(
        "Everything up to the run is ready — but actually executing tests needs the " +
          "worker that ships in M6. What you can do today: manage providers and build " +
          "datasets (upload, auto-detected columns, LLM generation with preview, approve) " +
          "in Settings → Datasets.",
      );
    }, 400);
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
          <div style={{ marginTop: "var(--space-5)" }}>
            <label className="form__label">System prompt:</label>
            <textarea placeholder="Enter your system prompt..." rows={3} disabled={loading} />
            <label className="form__label">Model:</label>
            <input type="text" placeholder="e.g. hermes3:8b, gpt-4o" disabled={loading} />
          </div>
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

        <div style={{ marginTop: "var(--space-5)" }}>
          <Button variant="primary" size="lg" loading={loading} onClick={handleStartTest}>
            {loading ? <Spinner size="sm" label="Checking your setup" /> : "Start test"}
          </Button>
        </div>

        {notice && (
          <div className="notice" role="status" style={{ marginTop: "var(--space-4)" }}>
            <strong>Runs ship in M6.</strong> {notice}
          </div>
        )}
      </section>

      <section
        className="card"
        aria-labelledby="demo-heading"
        style={{ marginTop: "var(--space-5)" }}
      >
        <div className="card__header">
          <h2 id="demo-heading">See it working first</h2>
          <ComingSoon detail="The built-in demo app ships in M10." />
        </div>
        <p className="card__hint">
          The demo runs a sample helpdesk app twice — a healthy version and a broken one — so you
          can see a GO and a NO-GO report without configuring anything.
        </p>
        <div style={{ marginTop: "var(--space-5)" }}>
          <Button variant="secondary" disabled title="Demo data ships in M10.">
            Try the demo
          </Button>
        </div>
      </section>
    </>
  );
}
