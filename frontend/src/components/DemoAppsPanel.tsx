import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../lib/api";
import {
  connectDemoApp,
  listDemoApps,
  type DemoApp,
  type DemoAppsResponse,
} from "../lib/demoApps";
import { Button } from "./Button";
import { Spinner } from "./Spinner";
import "../styles/settings.css";

type Platform = "windows" | "bash";

/**
 * Settings → Demo apps: the five local test subjects GreenLit can be pointed at.
 *
 * Every card says whether the app answers right now, what mode it reports, the
 * command to start it, and the same local-only warning before anything is saved.
 * Connecting saves an ordinary target through the API; nothing here starts a
 * process, because the app is a command the person runs.
 */
export function DemoAppsPanel() {
  const [data, setData] = useState<DemoAppsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [platform, setPlatform] = useState<Platform>("windows");
  const [copyNotice, setCopyNotice] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [connecting, setConnecting] = useState<string | null>(null);
  const [connected, setConnected] = useState<Record<string, string>>({});
  const [connectError, setConnectError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    listDemoApps()
      .then((response) => {
        if (active) setData(response);
      })
      .catch((exc: unknown) => {
        if (!active) return;
        setError(exc instanceof ApiError ? exc.message : "The catalog could not be loaded.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function copyCommand(app: DemoApp) {
    const command = platform === "windows" ? app.start_windows : app.start_bash;
    try {
      await navigator.clipboard.writeText(command);
      setCopyNotice(`Copied the ${platform} start command for ${app.name}.`);
    } catch {
      setCopyNotice("The browser refused to copy; select the command and copy it by hand.");
    }
  }

  async function connect(app: DemoApp) {
    setConnecting(app.id);
    setConnectError(null);
    try {
      const response = await connectDemoApp(app.id);
      setConnected((current) => ({ ...current, [app.id]: response.target.id }));
      setConfirming(null);
    } catch (exc: unknown) {
      setConnectError(
        exc instanceof ApiError ? exc.message : "That app could not be saved as a target.",
      );
    } finally {
      setConnecting(null);
    }
  }

  if (loading) {
    return (
      <div className="card" data-testid="demo-apps-loading">
        <Spinner label="Loading the demo apps" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="card" role="alert" data-testid="demo-apps-error">
        <p>{error ?? "The catalog could not be loaded."}</p>
      </div>
    );
  }

  return (
    <div data-testid="demo-apps-panel">
      <div className="settings__row" data-testid="demo-apps-platform">
        <span className="card__hint">Start command for</span>
        <Button
          variant={platform === "windows" ? "primary" : "secondary"}
          onClick={() => setPlatform("windows")}
          data-testid="demo-platform-windows"
        >
          Windows
        </Button>
        <Button
          variant={platform === "bash" ? "primary" : "secondary"}
          onClick={() => setPlatform("bash")}
          data-testid="demo-platform-bash"
        >
          bash
        </Button>
      </div>

      <p className="card__hint" data-testid="demo-apps-warning">
        {data.warning}
      </p>
      {copyNotice && (
        <p className="card__hint" role="status" data-testid="demo-copy-notice">
          {copyNotice}
        </p>
      )}
      {connectError && (
        <p className="field__error" role="alert" data-testid="demo-connect-error">
          {connectError}
        </p>
      )}

      <ul className="settings__list">
        {data.items.map((app) => {
          const up = app.status.state === "up";
          const command = platform === "windows" ? app.start_windows : app.start_bash;
          const targetId = connected[app.id];
          return (
            <li className="card" key={app.id} data-testid={`demo-card-${app.id}`}>
              <div className="card__header">
                <h3>{app.name}</h3>
                <span
                  className={`badge ${up ? "badge--go" : "badge--neutral"}`}
                  data-testid={`demo-status-${app.id}`}
                >
                  {up ? "running" : "not running"}
                </span>
              </div>
              <p>{app.description}</p>
              <p className="card__hint" data-testid={`demo-mode-${app.id}`}>
                {up && app.status.mode
                  ? `Mode: ${app.status.mode}${
                      app.status.provider && app.status.provider !== "none"
                        ? ` · ${app.status.provider} / ${app.status.model}`
                        : ""
                    }`
                  : "Mode: not reported, because the app is not running."}
              </p>
              <p className="card__hint">
                Modes: {app.modes.map((mode) => `${mode.mode} (${mode.shows})`).join("; ")}
              </p>
              <code className="code-block" data-testid={`demo-command-${app.id}`}>
                {command}
              </code>
              <div className="settings__row">
                <Button
                  variant="secondary"
                  onClick={() => void copyCommand(app)}
                  data-testid={`demo-copy-${app.id}`}
                >
                  Copy start command
                </Button>
                {targetId ? (
                  <>
                    <Link to="/settings" data-testid={`demo-open-${app.id}`}>
                      Open target
                    </Link>
                    <Link
                      to={`/tests/new?demo_app=${encodeURIComponent(app.id)}`}
                      data-testid={`demo-smoke-${app.id}`}
                    >
                      Run a smoke test
                    </Link>
                  </>
                ) : (
                  <Button
                    variant="primary"
                    onClick={() => setConfirming(app.id)}
                    data-testid={`demo-connect-${app.id}`}
                  >
                    Connect
                  </Button>
                )}
              </div>
              {confirming === app.id && !targetId && (
                <div className="card__hint" data-testid={`demo-confirm-${app.id}`}>
                  <p>
                    Connecting saves this local demo app as a target. It has no authentication
                    and is weak by design: never expose it to the internet.
                  </p>
                  <div className="settings__row">
                    <Button
                      variant="primary"
                      onClick={() => void connect(app)}
                      disabled={connecting === app.id}
                      data-testid={`demo-confirm-yes-${app.id}`}
                    >
                      {connecting === app.id ? "Saving…" : "Connect this app"}
                    </Button>
                    <Button
                      variant="secondary"
                      onClick={() => setConfirming(null)}
                      data-testid={`demo-confirm-no-${app.id}`}
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
