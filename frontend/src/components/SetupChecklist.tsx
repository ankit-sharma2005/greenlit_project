import { useState } from "react";
import { Link } from "react-router-dom";

import { Button } from "./Button";
import { ApiError } from "../lib/api";
import { testProvider, type ProviderTestResult } from "../lib/providers";

export interface SetupStepProvider {
  id: string;
  name: string;
  modelName: string;
}

export interface SetupChecklistProps {
  /** Saved providers that are active, i.e. usable by a prompt-app run. */
  providers: SetupStepProvider[];
  /** True once the target has answered a connection test in this session. */
  connectorTested: boolean;
  /** Approved dataset versions the next run can execute. */
  approvedDatasets: number;
  /** Focuses the target field, so "test the connector" is one click away. */
  onGoToTarget?: () => void;
}

/**
 * The three things a first test needs, with the real state of each (spec 8.4).
 *
 * Nothing here is decorative: the provider row is checked against the provider
 * itself on demand, the connector row reflects a real detection, and the dataset
 * row counts approved versions only — the same rule the run enforces.
 */
export function SetupChecklist({
  providers,
  connectorTested,
  approvedDatasets,
  onGoToTarget,
}: SetupChecklistProps) {
  const [checking, setChecking] = useState(false);
  const [result, setResult] = useState<ProviderTestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const provider = providers[0];
  const done = Boolean(provider) && connectorTested && approvedDatasets > 0;

  const check = async () => {
    if (!provider) return;
    setChecking(true);
    setError(null);
    setResult(null);
    try {
      setResult(await testProvider(provider.id));
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "Could not test the provider. Check that the API is running.",
      );
    } finally {
      setChecking(false);
    }
  };

  const providerState = !provider
    ? "No provider saved"
    : result === null
      ? `${provider.name} · ${provider.modelName} (not checked yet)`
      : result.success
        ? `${provider.name} reachable · ${result.latency_ms} ms`
        : `${provider.name} did not answer${result.message ? `: ${result.message}` : ""}`;

  return (
    <section className="card" aria-labelledby="setup-heading" data-testid="setup-checklist">
      <div className="card__header">
        <h2 id="setup-heading">Setup</h2>
        <span className="badge badge--neutral" data-testid="setup-progress">
          {[Boolean(provider), connectorTested, approvedDatasets > 0].filter(Boolean).length} of 3
        </span>
      </div>

      {done ? (
        <p className="card__hint" data-testid="setup-ready">
          Everything a test needs is in place: a provider, a tested connector and an approved
          dataset.
        </p>
      ) : (
        <ul
          data-testid="setup-steps"
          style={{ margin: "0 0 var(--space-3)", paddingLeft: "var(--space-4)" }}
        >
          <li data-testid="setup-provider" data-done={Boolean(provider)}>
            <strong>Provider</strong>{" "}
            <span data-testid="setup-provider-state">{providerState}</span>
            {provider ? (
              <Button
                variant="secondary"
                onClick={() => void check()}
                loading={checking}
                disabled={checking}
                data-testid="setup-check-provider"
              >
                Check now
              </Button>
            ) : (
              <Link to="/settings" data-testid="setup-provider-link">
                Add a provider in Settings → Providers
              </Link>
            )}
          </li>
          <li data-testid="setup-connector" data-done={connectorTested}>
            <strong>Connector</strong>{" "}
            {connectorTested ? (
              "the target answered a connection test"
            ) : onGoToTarget ? (
              <Button variant="secondary" onClick={onGoToTarget} data-testid="setup-go-target">
                Test your target
              </Button>
            ) : (
              "no connection test yet"
            )}
          </li>
          <li data-testid="setup-dataset" data-done={approvedDatasets > 0}>
            <strong>Dataset</strong>{" "}
            {approvedDatasets > 0 ? (
              `${approvedDatasets} approved version${approvedDatasets === 1 ? "" : "s"} ready`
            ) : (
              <Link to="/settings" data-testid="setup-dataset-link">
                Approve a dataset in Settings → Datasets
              </Link>
            )}
          </li>
        </ul>
      )}

      {error ? (
        <p className="form-error" role="alert" data-testid="setup-error">
          {error}
        </p>
      ) : null}
    </section>
  );
}
