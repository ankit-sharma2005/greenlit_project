import { useCallback, useEffect, useState } from "react";

import { ApiError } from "../lib/api";
import {
  createProvider,
  deleteProvider,
  listProviders,
  testProvider,
  updateProvider,
  type Provider,
  type ProviderTestResult,
} from "../lib/providers";
import { Button } from "./Button";
import { Spinner } from "./Spinner";

function healthBadge(result: ProviderTestResult | null) {
  if (!result) return <span className="badge badge--neutral">unknown</span>;
  if (result.success) return <span className="badge badge--go">healthy</span>;
  return <span className="badge badge--nogo">unreachable</span>;
}

export function ProvidersPanel() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [name, setName] = useState("Ollama");
  const [kind, setKind] = useState("ollama");
  const [modelName, setModelName] = useState("hermes3:8b");
  const [baseUrl, setBaseUrl] = useState("http://host.docker.internal:11434/v1");
  const [apiKey, setApiKey] = useState("");
  const [isActive] = useState(true);

  const [testResults, setTestResults] = useState<Record<string, ProviderTestResult>>({});

  const showError = (caught: unknown) => {
    if (caught instanceof ApiError) {
      setError(caught.message);
    } else {
      setError("Something went wrong. Try again.");
    }
  };

  const refresh = useCallback(async () => {
    try {
      const items = await listProviders();
      setProviders(items);
    } catch (caught) {
      showError(caught);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleCreate = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      await createProvider({
        name: name.trim(),
        kind,
        model_name: modelName.trim(),
        base_url: baseUrl.trim() || null,
        api_key: apiKey.trim() || null,
        is_active: isActive,
      });
      setNotice(`Provider “${name.trim()}” created.`);
      setApiKey("");
      await refresh();
    } catch (caught) {
      showError(caught);
    } finally {
      setBusy(false);
    }
  };

  const handleTest = async (id: string) => {
    setError(null);
    try {
      const result = await testProvider(id);
      setTestResults((prev) => ({ ...prev, [id]: result }));
      setNotice(result.success ? "Connection successful." : result.message);
    } catch (caught) {
      showError(caught);
    }
  };

  const handleToggleActive = async (provider: Provider) => {
    try {
      await updateProvider(provider.id, { is_active: !provider.is_active });
      await refresh();
    } catch (caught) {
      showError(caught);
    }
  };

  const handleDelete = async (provider: Provider) => {
    if (!window.confirm(`Delete provider “${provider.name}”?`)) return;
    try {
      await deleteProvider(provider.id);
      await refresh();
    } catch (caught) {
      showError(caught);
    }
  };

  const setOllamaDefaults = () => {
    setName("Ollama");
    setKind("ollama");
    setModelName("hermes3:8b");
    setBaseUrl("http://host.docker.internal:11434/v1");
    setApiKey("");
  };

  const setOpenAICompatible = () => {
    setName("OpenAI Compatible");
    setKind("openai-compatible");
    setModelName("gpt-4o-mini");
    setBaseUrl("https://api.openai.com/v1");
    setApiKey("");
  };

  return (
    <div>
      <section className="card" aria-labelledby="providers-add">
        <div className="card__header">
          <h3 id="providers-add">Add provider</h3>
          <p className="card__hint">
            Defaults: Ollama at http://host.docker.internal:11434/v1 with model hermes3:8b (free,
            local). OpenAI-compatible providers need a base URL and API key.
          </p>
        </div>
        <div className="datasets__actions" style={{ marginBottom: "var(--space-3)" }}>
          <Button variant="secondary" onClick={setOllamaDefaults}>
            Use Ollama defaults
          </Button>
          <Button variant="secondary" onClick={setOpenAICompatible}>
            Use OpenAI-compatible
          </Button>
        </div>
        <form onSubmit={handleCreate} className="datasets__upload">
          <label className="form__label" htmlFor="provider-name">
            Name:
          </label>
          <input
            id="provider-name"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            disabled={busy}
          />
          <label className="form__label" htmlFor="provider-kind">
            Kind:
          </label>
          <select
            id="provider-kind"
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            disabled={busy}
          >
            <option value="ollama">ollama</option>
            <option value="openai-compatible">openai-compatible</option>
            <option value="groq">groq</option>
          </select>
          <label className="form__label" htmlFor="provider-model">
            Model:
          </label>
          <input
            id="provider-model"
            type="text"
            value={modelName}
            onChange={(e) => setModelName(e.target.value)}
            required
            disabled={busy}
          />
          <label className="form__label" htmlFor="provider-baseurl">
            Base URL:
          </label>
          <input
            id="provider-baseurl"
            type="text"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            disabled={busy}
          />
          {kind !== "ollama" && (
            <>
              <label className="form__label" htmlFor="provider-key">
                API Key:
              </label>
              <input
                id="provider-key"
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="sk-..."
                disabled={busy}
              />
              <p className="card__hint">
                Keys are encrypted at rest and never returned by the API.
              </p>
            </>
          )}
          <div className="datasets__actions" style={{ marginTop: "var(--space-3)" }}>
            <Button type="submit" variant="primary" loading={busy}>
              {busy ? <Spinner size="sm" label="Creating" /> : "Add provider"}
            </Button>
          </div>
        </form>
      </section>

      {error && (
        <p className="form-error" role="alert" style={{ marginTop: "var(--space-4)" }}>
          {error}
        </p>
      )}
      {notice && (
        <div className="notice" role="status" style={{ marginTop: "var(--space-4)" }}>
          {notice}
        </div>
      )}

      <section
        className="card"
        aria-labelledby="providers-list"
        style={{ marginTop: "var(--space-5)" }}
      >
        <div className="card__header">
          <h3 id="providers-list">Providers</h3>
        </div>
        {loading ? (
          <Spinner size="md" label="Loading providers" showLabel />
        ) : providers.length === 0 ? (
          <p className="card__hint">
            No providers yet. Add Ollama or an OpenAI-compatible provider above.
          </p>
        ) : (
          <table className="datasets__table">
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Kind</th>
                <th scope="col">Model</th>
                <th scope="col">Base URL</th>
                <th scope="col">Status</th>
                <th scope="col">Health</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {providers.map((provider) => (
                <tr key={provider.id}>
                  <td>{provider.name}</td>
                  <td>{provider.kind}</td>
                  <td>{provider.model_name}</td>
                  <td>{provider.base_url || "—"}</td>
                  <td>
                    {provider.is_active ? (
                      <span className="badge badge--go">active</span>
                    ) : (
                      <span className="badge badge--neutral">inactive</span>
                    )}
                  </td>
                  <td>{healthBadge(testResults[provider.id] || null)}</td>
                  <td>
                    <div className="datasets__actions">
                      <Button variant="secondary" onClick={() => void handleTest(provider.id)}>
                        Test connection
                      </Button>
                      <Button variant="secondary" onClick={() => void handleToggleActive(provider)}>
                        {provider.is_active ? "Disable" : "Enable"}
                      </Button>
                      <Button variant="secondary" onClick={() => void handleDelete(provider)}>
                        Delete
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
