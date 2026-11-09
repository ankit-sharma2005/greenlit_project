import { useEffect, useState } from "react";

import { Button } from "./Button";
import { ApiError } from "../lib/api";
import {
  fetchPreferences,
  updatePreferences,
  type ModelChoice,
  type ModelRole,
  type Preferences,
} from "../lib/preferences";
import { listProviders, type Provider } from "../lib/providers";
import "../styles/settings.css";

interface RoleChoice {
  providerId: string;
  model: string;
}

const ROLES: { role: ModelRole; label: string; hint: string }[] = [
  {
    role: "judge",
    label: "Judge model",
    hint: "Grades every answer against the expected one.",
  },
  {
    role: "target",
    label: "Model under test",
    hint: "Used by the prompt-only entry point; a run can override it.",
  },
  {
    role: "generator",
    label: "Dataset generator model",
    hint: "Writes draft test cases you review before anything is usable.",
  },
  {
    role: "analyst",
    label: "Analyst model",
    hint: "Explains a finished run in words. It never changes the verdict.",
  },
];

/** The analyst is optional: a run can be read without one, so saving does not require it. */
const REQUIRED_ROLES: readonly ModelRole[] = ["judge", "target", "generator"];

const EMPTY: Record<ModelRole, RoleChoice> = {
  judge: { providerId: "", model: "" },
  target: { providerId: "", model: "" },
  generator: { providerId: "", model: "" },
  analyst: { providerId: "", model: "" },
};

function fromChoice(choice: ModelChoice | null | undefined): RoleChoice {
  return { providerId: choice?.provider_id ?? "", model: choice?.model ?? "" };
}

/**
 * Settings → Providers and models: the default provider and model for each role.
 *
 * The three choices are saved to the account, so they follow the user to another
 * browser. A generator that is the same provider and model as the judge is shown as a
 * warning and needs an explicit confirmation, because the model that wrote the questions
 * would also grade them. The panel never shows or asks for a provider key.
 */
export function ModelDefaultsPanel() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [theme, setTheme] = useState<Preferences["theme"]>("dark");
  const [choices, setChoices] = useState<Record<ModelRole, RoleChoice>>(EMPTY);
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState(false);

  useEffect(() => {
    let active = true;
    Promise.all([listProviders(), fetchPreferences()])
      .then(([list, preferences]) => {
        if (!active) return;
        setProviders(list.filter((provider) => provider.is_active));
        setTheme(preferences.theme);
        setChoices({
          judge: fromChoice(preferences.judge),
          target: fromChoice(preferences.target),
          generator: fromChoice(preferences.generator),
          analyst: fromChoice(preferences.analyst),
        });
      })
      .catch(() => {
        if (active) setError("Could not load your saved model choices. Reload to try again.");
      })
      .finally(() => {
        if (active) setLoaded(true);
      });
    return () => {
      active = false;
    };
  }, []);

  function chooseProvider(role: ModelRole, providerId: string) {
    const provider = providers.find((entry) => entry.id === providerId);
    setChoices((current) => ({
      ...current,
      [role]: { providerId, model: provider?.model_name ?? "" },
    }));
    setConfirmed(false);
  }

  function chooseModel(role: ModelRole, model: string) {
    setChoices((current) => ({ ...current, [role]: { ...current[role], model } }));
    setConfirmed(false);
  }

  const complete = REQUIRED_ROLES.every(
    (role) => choices[role].providerId !== "" && choices[role].model.trim() !== "",
  );
  const generatorMatchesJudge =
    choices.generator.providerId !== "" &&
    choices.generator.providerId === choices.judge.providerId &&
    choices.generator.model.trim().toLowerCase() === choices.judge.model.trim().toLowerCase();

  async function save() {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const payload: Partial<Record<ModelRole, ModelChoice>> = {};
      for (const { role } of ROLES) {
        const choice = choices[role];
        const filled = choice.providerId !== "" && choice.model.trim() !== "";
        // An unfilled optional role is left out, so the stored choice survives.
        if (role === "analyst" && !filled) continue;
        payload[role] = {
          provider_id: choice.providerId,
          model: choice.model.trim(),
        };
      }
      const saved = await updatePreferences(theme, payload);
      setChoices({
        judge: fromChoice(saved.judge),
        target: fromChoice(saved.target),
        generator: fromChoice(saved.generator),
        analyst: saved.analyst ? fromChoice(saved.analyst) : choices.analyst,
      });
      setNotice("Saved to your account. New runs use these models unless a run overrides them.");
      setConfirmed(false);
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "Could not save your choices. Check the providers and try again.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="card" aria-labelledby="model-defaults-heading" data-testid="model-defaults">
      <div className="card__header">
        <h3 id="model-defaults-heading">Default models</h3>
        <p className="card__hint">
          One provider and model per job. A run can override the model under test.
        </p>
      </div>

      {providers.length === 0 && loaded ? (
        <p className="card__hint" data-testid="model-defaults-no-providers">
          No active provider yet. Add one above, then choose the defaults here.
        </p>
      ) : null}

      {ROLES.map(({ role, label, hint }) => (
        <div key={role} data-testid={`model-defaults-${role}`} style={{ marginTop: "var(--space-4)" }}>
          <label className="form__label" htmlFor={`model-defaults-${role}-provider`}>
            {label}:
          </label>
          <select
            id={`model-defaults-${role}-provider`}
            data-testid={`model-defaults-${role}-provider`}
            value={choices[role].providerId}
            onChange={(event) => chooseProvider(role, event.target.value)}
            disabled={saving || !loaded}
          >
            <option value="">Pick a provider</option>
            {providers.map((provider) => (
              <option key={provider.id} value={provider.id}>
                {provider.name}
              </option>
            ))}
          </select>
          <input
            aria-label={`${label} model`}
            data-testid={`model-defaults-${role}-model`}
            type="text"
            value={choices[role].model}
            onChange={(event) => chooseModel(role, event.target.value)}
            placeholder="e.g. llama3, gpt-4o-mini"
            disabled={saving || !loaded}
            style={{ marginTop: "var(--space-2)" }}
          />
          <p className="card__hint">{hint}</p>
        </div>
      ))}

      {generatorMatchesJudge ? (
        <div className="form-error" role="alert" data-testid="model-defaults-warning">
          <p>
            The dataset generator is the same provider and model as the judge. The model that
            writes the questions would also grade them.
          </p>
          <label>
            <input
              type="checkbox"
              data-testid="model-defaults-confirm"
              checked={confirmed}
              onChange={(event) => setConfirmed(event.target.checked)}
            />{" "}
            I understand, and want to use it anyway.
          </label>
        </div>
      ) : null}

      {error ? (
        <p className="form-error" role="alert" data-testid="model-defaults-error">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="notice" role="status" data-testid="model-defaults-notice">
          {notice}
        </p>
      ) : null}

      <div className="datasets__actions" style={{ marginTop: "var(--space-4)" }}>
        <Button
          type="button"
          variant="primary"
          onClick={() => void save()}
          loading={saving}
          disabled={!loaded || !complete || (generatorMatchesJudge && !confirmed)}
          data-testid="model-defaults-save"
        >
          Save defaults
        </Button>
      </div>
    </section>
  );
}
