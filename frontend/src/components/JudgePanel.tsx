import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError } from "../lib/api";
import {
  createJudgeProfile,
  deleteJudgeProfile,
  listJudgeProfiles,
  selectJudgeProfile,
  type JudgeProfile,
} from "../lib/judgeProfiles";
import { listProviders, type Provider } from "../lib/providers";
import { Button } from "./Button";
import { Spinner } from "./Spinner";

const DEFAULT_MAX_TOKENS = 512;

/**
 * Settings → Judge: pick which saved provider and model grades a run's answers.
 *
 * Temperature is fixed at 0 by the API (the same inputs must reproduce the same
 * verdict), so it is shown as a fact rather than offered as a control. The
 * self-grading warning comes from the server, which knows every saved provider.
 */
export function JudgePanel() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [profiles, setProfiles] = useState<JudgeProfile[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [name, setName] = useState("The judge");
  const [providerId, setProviderId] = useState("");
  const [model, setModel] = useState("");
  const [maxTokens, setMaxTokens] = useState(String(DEFAULT_MAX_TOKENS));
  const [maxCases, setMaxCases] = useState("");

  const showError = (caught: unknown) => {
    setError(caught instanceof ApiError ? caught.message : "Something went wrong. Try again.");
  };

  const refresh = useCallback(async () => {
    try {
      const [nextProviders, nextProfiles] = await Promise.all([
        listProviders(),
        listJudgeProfiles(),
      ]);
      setProviders(nextProviders);
      setProfiles(nextProfiles.items);
      setSelectedId(nextProfiles.selected_id);
      setProviderId((current) => current || nextProviders[0]?.id || "");
    } catch (caught) {
      showError(caught);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const activeProvider = providers.find((provider) => provider.id === providerId) ?? null;

  // The suggested model follows the chosen provider until the user types one.
  useEffect(() => {
    if (activeProvider) setModel(activeProvider.model_name);
  }, [activeProvider]);

  const selected = useMemo(
    () => profiles.find((profile) => profile.id === selectedId) ?? null,
    [profiles, selectedId],
  );

  const warnings = useMemo(() => {
    const list = selected ? selected.warnings : (profiles[0]?.warnings ?? []);
    return list;
  }, [profiles, selected]);

  const handleCreate = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      const created = await createJudgeProfile({
        name: name.trim() || "The judge",
        provider_id: providerId || null,
        model: model.trim() || null,
        max_tokens: Number(maxTokens) || DEFAULT_MAX_TOKENS,
        // An empty box means "grade every case", which is the default.
        max_cases: maxCases.trim() ? Number(maxCases) : null,
      });
      setNotice(
        created.is_selected
          ? `The judge “${created.name}” is saved and will grade your next run.`
          : `The judge “${created.name}” is saved. Select it to make it the default.`,
      );
      await refresh();
    } catch (caught) {
      showError(caught);
    } finally {
      setBusy(false);
    }
  };

  const handleSelect = async (profile: JudgeProfile) => {
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      const updated = await selectJudgeProfile(profile.id);
      setNotice(`“${updated.name}” will grade the answers of your next run.`);
      await refresh();
    } catch (caught) {
      showError(caught);
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async (profile: JudgeProfile) => {
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      await deleteJudgeProfile(profile.id);
      setNotice(`“${profile.name}” was deleted.`);
      await refresh();
    } catch (caught) {
      showError(caught);
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <section className="card" data-testid="judge-panel">
        <Spinner size="md" label="Loading the judge settings" />
      </section>
    );
  }

  return (
    <section className="card" aria-labelledby="judge-heading" data-testid="judge-panel">
      <div className="card__header">
        <h2 id="judge-heading">Judge</h2>
        <span className="badge badge--neutral">rubric 1.0 · temperature 0</span>
      </div>
      <p className="card__hint">
        The judge grades each answer against the expected answer and adds an{" "}
        <code>answer_quality</code> metric. A judge that cannot be reached, or is unsure of itself,
        sends the verdict to REVIEW instead of guessing. A different model than the app under test
        gives a more independent score.
      </p>

      {error ? (
        <p className="form-error" role="alert" data-testid="judge-error">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="form-success" role="status" data-testid="judge-notice">
          {notice}
        </p>
      ) : null}

      {providers.length === 0 ? (
        <p className="card__hint" data-testid="judge-no-providers">
          No provider is saved yet, so there is nothing for the judge to call. Add one in Settings →
          Providers first.
        </p>
      ) : (
        <form
          onSubmit={(event) => void handleCreate(event)}
          style={{ marginTop: "var(--space-4)" }}
        >
          <div className="form__field">
            <label className="form__label" htmlFor="judge-provider">
              Provider:
            </label>
            <select
              id="judge-provider"
              data-testid="judge-provider"
              value={providerId}
              onChange={(event) => setProviderId(event.target.value)}
              disabled={busy}
            >
              {providers.map((provider) => (
                <option key={provider.id} value={provider.id}>
                  {provider.name} ({provider.model_name})
                </option>
              ))}
            </select>
          </div>

          <div className="form__field">
            <label className="form__label" htmlFor="judge-model">
              Model:
            </label>
            <input
              id="judge-model"
              data-testid="judge-model"
              value={model}
              onChange={(event) => setModel(event.target.value)}
              disabled={busy}
            />
            <p className="form__hint">Defaults to the provider&apos;s own model.</p>
          </div>

          <div className="form__field">
            <label className="form__label" htmlFor="judge-name">
              Profile name:
            </label>
            <input
              id="judge-name"
              data-testid="judge-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              disabled={busy}
            />
          </div>

          <div className="form__field">
            <label className="form__label" htmlFor="judge-max-cases">
              Judge at most (cases):
            </label>
            <input
              id="judge-max-cases"
              data-testid="judge-max-cases"
              type="number"
              min={1}
              max={1000}
              placeholder="every case"
              value={maxCases}
              onChange={(event) => setMaxCases(event.target.value)}
              disabled={busy}
            />
            <p className="form__hint">
              A per-run cost guard. Cases beyond the cap are left out of <code>answer_quality</code>{" "}
              rather than scored zero, and the verdict card says how many of how many were judged.
              Leave empty to judge every case.
            </p>
          </div>

          <div className="form__field">
            <label className="form__label" htmlFor="judge-max-tokens">
              Max tokens:
            </label>
            <input
              id="judge-max-tokens"
              data-testid="judge-max-tokens"
              type="number"
              min={64}
              max={4096}
              value={maxTokens}
              onChange={(event) => setMaxTokens(event.target.value)}
              disabled={busy}
            />
          </div>

          <Button type="submit" variant="primary" loading={busy} data-testid="judge-save">
            Save judge
          </Button>
        </form>
      )}

      {warnings.length > 0 ? (
        <p className="form-warning" role="status" data-testid="judge-warning">
          {warnings.join(" ")}
        </p>
      ) : null}

      <h3 style={{ marginTop: "var(--space-5)" }}>Saved judges</h3>
      {profiles.length === 0 ? (
        <p className="card__hint" data-testid="judge-none">
          No judge saved yet. Runs will not be judged until you save one.
        </p>
      ) : (
        <table className="results__table" data-testid="judge-table">
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Model</th>
              <th scope="col">Rubric</th>
              <th scope="col">Cap</th>
              <th scope="col">State</th>
              <th scope="col">Actions</th>
            </tr>
          </thead>
          <tbody>
            {profiles.map((profile) => (
              <tr key={profile.id}>
                <td>{profile.name}</td>
                <td>
                  {profile.model ?? "—"}
                  {profile.provider_name ? (
                    <span className="card__hint"> · {profile.provider_name}</span>
                  ) : (
                    <span className="card__hint"> · provider deleted</span>
                  )}
                </td>
                <td>
                  {profile.rubric_version} · {profile.temperature.toFixed(1)}
                </td>
                <td data-testid={`judge-cap-${profile.name}`}>
                  {profile.max_cases === null ? "all cases" : `${profile.max_cases} cases`}
                </td>
                <td>
                  {profile.is_selected ? (
                    <span className="results__state--pass">default</span>
                  ) : (
                    <span className="results__state--skip">saved</span>
                  )}
                </td>
                <td>
                  <div className="datasets__actions">
                    <Button
                      type="button"
                      variant="secondary"
                      onClick={() => void handleSelect(profile)}
                      disabled={busy || profile.is_selected}
                      data-testid={`judge-select-${profile.name}`}
                    >
                      Use this judge
                    </Button>
                    <Button
                      type="button"
                      variant="secondary"
                      onClick={() => void handleDelete(profile)}
                      disabled={busy}
                      data-testid={`judge-delete-${profile.name}`}
                    >
                      Delete
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {selected ? (
        <p className="card__hint" data-testid="judge-selected">
          Answers will be graded by {selected.model ?? "the provider&apos;s model"} using rubric{" "}
          {selected.rubric_version}.
        </p>
      ) : null}
    </section>
  );
}
