import { useState } from "react";

import { Button } from "../components/Button";
import { ComingSoon } from "../components/ComingSoon";
import { Spinner } from "../components/Spinner";

/** Home: one page where a first-time user points GreenLit at an app and gets a verdict. */
export function NewTestPage() {
  const [connector, setConnector] = useState<"http_endpoint" | "prompt_app" | "upload_outputs">(
    "http_endpoint",
  );
  const [url, setUrl] = useState("");
  const [showCurl, setShowCurl] = useState(false);
  const [runsOnMyComputer, setRunsOnMyComputer] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleConnecterChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setConnector(e.target.value as "http_endpoint" | "prompt_app" | "upload_outputs");
    setUrl("");
  };

  const handleUrlChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setUrl(e.target.value);
  };

  const handleCurlToggle = () => {
    setShowCurl(!showCurl);
  };

  const handleRunOnMyComputerToggle = () => {
    setRunsOnMyComputer(!runsOnMyComputer);
  };

  const handleStartTest = () => {
    setLoading(true);
    // TODO: In M3, start the test with the selected connector type
    setLoading(false);
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
          <p className="page__subtitle">
            Select how GreenLit should connect to your app.
          </p>
        </div>

        <p className="card__hint">
          Three entry points are available here: an HTTP endpoint, a prompt app (system prompt
          plus model), or uploaded outputs (CSV or JSON). Other entry points (Python function,
          Docker image, Git repository, CLI command, Proxy mode, Website URL, MCP server) are
          coming soon.
        </p>

        <div style={{ marginTop: "var(--space-5)" }}>
          <label className="form__label" htmlFor="connector-select">
            Connector type:
          </label>
          <select
            id="connector-select"
            value={connector}
            onChange={handleConnecterChange}
            disabled={loading}
          >
            <option value="http_endpoint">HTTP endpoint</option>
            <option value="prompt_app">Prompt app (system prompt + model)</option>
            <option value="upload_outputs">Upload outputs (CSV/JSON)</option>
            <optgroup label="Coming soon">
              <option disabled>
                Python function (traced)
              </option>
              <option disabled>
                Built-in RAG app
              </option>
              <option disabled>
                Python SDK (traced)
              </option>
              <option disabled>
                Docker image
              </option>
              <option disabled>
                Git repository
              </option>
              <option disabled>
                CLI command
              </option>
              <option disabled>
                Website URL
              </option>
              <option disabled>
                MCP server
              </option>
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
              onChange={handleUrlChange}
              placeholder="https://example.com/v1/models"
              disabled={loading}
            />
            <button
              onClick={handleCurlToggle}
              className="form__curl-button"
              disabled={loading}
            >
              {showCurl ? "Hide cURL" : "Paste cURL"}
            </button>
          </div>
        )}

        {connector === "prompt_app" && (
          <div style={{ marginTop: "var(--space-5)" }}>
            <label className="form__label">System prompt:</label>
            <textarea
              placeholder="Enter your system prompt..."
              rows={3}
              disabled={loading}
            ></textarea>
            <label className="form__label">Model:</label>
            <input
              type="text"
              placeholder="e.g. gpt-4, claude-3, llama3"
              disabled={loading}
            />
          </div>
        )}

        {connector === "upload_outputs" && (
          <div style={{ marginTop: "var(--space-5)" }}>
            <label className="form__label">Upload file:</label>
            <input
              type="file"
              disabled={loading}
            />
            <p className="form__hint">
              CSV or JSON file containing output data
            </p>
          </div>
        )}

        <div className="form__run-on-computer">
          <input
            type="checkbox"
            id="runs-on-my-computer"
            checked={runsOnMyComputer}
            onChange={handleRunOnMyComputerToggle}
            disabled={loading}
          />
          <label htmlFor="runs-on-my-computer">
            This app runs on my computer
          </label>
          <p className="form__hint">
            GreenLit will test your local app via tunnel (ngrok required)
          </p>
        </div>

        <div style={{ marginTop: "var(--space-5)" }}>
          <Button
            variant="primary"
            size="lg"
            disabled={loading}
            onClick={handleStartTest}
          >
            {loading ? (
              <Spinner size="md" label="Running test..." showLabel />
            ) : (
              "Start test"
            )}
          </Button>
        </div>
      </section>

      <section className="card" aria-labelledby="demo-heading">
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