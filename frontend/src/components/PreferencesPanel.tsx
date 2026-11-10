import { useEffect, useState } from "react";

import { DEFAULT_THEME, THEME_OPTIONS, type Theme } from "../lib/theme";
import { fetchPreferences, updatePreferences } from "../lib/preferences";
import type {
  DefaultEntryPoint,
  DefaultTestType,
  DisplayPreferences,
} from "../lib/preferences";
import { timeZoneChoices } from "../lib/dates";
import { useTheme } from "../theme/themeContext";
import { Button } from "./Button";
import "../styles/settings.css";

// The labels live here rather than in the API client: this panel is the only
// place that renders them, and the client stays a plain request helper.
const ENTRY_POINTS: { value: DefaultEntryPoint; label: string }[] = [
  { value: "http_endpoint", label: "HTTP endpoint" },
  { value: "mcp_server", label: "MCP server (tool call)" },
  { value: "prompt_app", label: "Prompt app (system prompt + model)" },
  { value: "upload_outputs", label: "Upload outputs (CSV/JSON)" },
];
const TEST_TYPES: { value: DefaultTestType; label: string }[] = [
  { value: "quality", label: "Quality (answer match and judge)" },
  { value: "safety", label: "Safety (attack probes and over-refusal)" },
  { value: "operations", label: "Operations (latency, errors, tokens)" },
];

/**
 * Settings → Preferences: appearance, applied at once and saved to the account.
 *
 * There is no separate Save button on purpose — picking a theme is the save, so
 * the preview and the stored value can never disagree. A failed save keeps the
 * choice for this browser and says so, with a retry.
 */
export function PreferencesPanel() {
  const { theme, resolved, saving, error, setTheme, resetTheme } = useTheme();
  const [notice, setNotice] = useState<string | null>(null);
  const [retry, setRetry] = useState<Theme | null>(null);
  // The other fields: loaded once, then saved one control at a time.
  const [display, setDisplay] = useState<DisplayPreferences>({});
  const [displayLoaded, setDisplayLoaded] = useState(false);
  const [displaySaving, setDisplaySaving] = useState(false);
  const [displayError, setDisplayError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchPreferences()
      .then((stored) => {
        if (cancelled) return;
        setDisplay({
          entry_point: stored.entry_point ?? undefined,
          test_types: stored.test_types ?? undefined,
          time_zone: stored.time_zone ?? undefined,
          show_full_answers: stored.show_full_answers ?? undefined,
        });
      })
      .catch(() => {
        /* an unreadable document keeps the defaults; the theme retry reports the error */
      })
      .finally(() => {
        if (!cancelled) setDisplayLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function saveDisplay(next: DisplayPreferences, successMessage: string) {
    setNotice(null);
    setDisplayError(null);
    setDisplaySaving(true);
    try {
      // Every key the panel owns is sent together, so one save never clears another.
      const saved = await updatePreferences(theme, {}, next);
      setDisplay({
        entry_point: saved.entry_point ?? undefined,
        test_types: saved.test_types ?? undefined,
        time_zone: saved.time_zone ?? undefined,
        show_full_answers: saved.show_full_answers ?? undefined,
      });
      setNotice(successMessage);
    } catch {
      setDisplayError("That preference could not be saved. Check your connection and try again.");
    } finally {
      setDisplaySaving(false);
    }
  }

  const toggleTestType = (name: DefaultTestType, on: boolean) => {
    const current = display.test_types ?? [];
    const next = on
      ? TEST_TYPES.map((option) => option.value).filter(
          (type) => type === name || current.includes(type),
        )
      : current.filter((type) => type !== name);
    void saveDisplay({ ...display, test_types: next }, "Default test types saved.");
  };

  async function choose(next: Theme, successMessage: string) {
    setNotice(null);
    const saved = await setTheme(next);
    setRetry(saved ? null : next);
    if (saved) setNotice(successMessage);
  }

  async function reset() {
    setNotice(null);
    const saved = await resetTheme();
    setRetry(saved ? null : DEFAULT_THEME);
    if (saved) setNotice("Preferences reset to the default theme.");
  }

  return (
    <section className="card" aria-labelledby="preferences-heading" data-testid="preferences-panel">
      <div className="card__header">
        <h2 id="preferences-heading">Preferences</h2>
        <span className="badge badge--neutral" data-testid="preferences-save-state">
          {saving ? "Saving…" : "Saved to your account"}
        </span>
      </div>
      <p className="card__hint">
        Your preferences belong to your account, so they follow you to another browser instead of
        belonging to whoever used this computer last. The chosen theme also stays cached here, which
        is why a reload does not flash the wrong colours.
      </p>

      {error ? (
        <div className="form-error" role="alert" data-testid="preferences-error">
          <p>{error}</p>
          {retry ? (
            <Button
              type="button"
              variant="secondary"
              disabled={saving}
              onClick={() => void choose(retry, "Preference saved to your account.")}
              data-testid="preferences-retry"
            >
              Try again
            </Button>
          ) : null}
        </div>
      ) : null}
      {notice ? (
        <p className="notice" role="status" data-testid="preferences-notice">
          {notice}
        </p>
      ) : null}

      <fieldset className="theme-options">
        <legend className="theme-options__legend">Appearance</legend>
        {THEME_OPTIONS.map((option) => (
          <label key={option.value} className="theme-option">
            <input
              type="radio"
              name="theme"
              value={option.value}
              data-testid={`theme-${option.value}`}
              checked={theme === option.value}
              disabled={saving}
              onChange={() => void choose(option.value, "Appearance saved.")}
            />
            <span className="theme-option__text">
              <span className="theme-option__label">{option.label}</span>
              <span className="theme-option__detail">{option.detail}</span>
            </span>
          </label>
        ))}
      </fieldset>

      <p className="card__hint" data-testid="preferences-current">
        Showing the <strong>{resolved}</strong> theme
        {theme === "system" ? " (following your system setting)" : ""}.
      </p>

      {displayError ? (
        <div className="form-error" role="alert" data-testid="preferences-display-error">
          <p>{displayError}</p>
        </div>
      ) : null}

      <fieldset className="preference-fields">
        <legend className="theme-options__legend">Defaults for a new test</legend>
        <label className="form__label" htmlFor="preferences-entry-point">
          Entry point
        </label>
        <select
          id="preferences-entry-point"
          data-testid="preferences-entry-point"
          value={display.entry_point ?? ""}
          disabled={!displayLoaded || displaySaving}
          onChange={(event) =>
            void saveDisplay(
              {
                ...display,
                entry_point: (event.target.value || undefined) as DefaultEntryPoint | undefined,
              },
              "Default entry point saved.",
            )
          }
        >
          <option value="">No default (HTTP endpoint)</option>
          {ENTRY_POINTS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <p className="card__hint">
          New Test opens on this form. Anything you have already typed there is never replaced.
        </p>

        <span className="form__label">Test types</span>
        {TEST_TYPES.map((option) => (
          <label key={option.value} className="preference-check">
            <input
              type="checkbox"
              data-testid={`preferences-test-type-${option.value}`}
              checked={(display.test_types ?? []).includes(option.value)}
              disabled={!displayLoaded || displaySaving}
              onChange={(event) => toggleTestType(option.value, event.target.checked)}
            />
            <span>{option.label}</span>
          </label>
        ))}
        <p className="card__hint">
          Tick what a new test should run. Nothing ticked means the form keeps its own defaults.
        </p>

        <label className="form__label" htmlFor="preferences-time-zone">
          Time zone
        </label>
        <select
          id="preferences-time-zone"
          data-testid="preferences-time-zone"
          value={display.time_zone ?? ""}
          disabled={!displayLoaded || displaySaving}
          onChange={(event) =>
            void saveDisplay(
              { ...display, time_zone: event.target.value || undefined },
              "Time zone saved.",
            )
          }
        >
          <option value="">This browser’s time zone</option>
          {timeZoneChoices().map((zone) => (
            <option key={zone} value={zone}>
              {zone}
            </option>
          ))}
        </select>
        <p className="card__hint">
          Dates and times are shown in this zone. The conversion happens in your browser, so the
          server never has to know where you are.
        </p>

        <label className="preference-check">
          <input
            type="checkbox"
            data-testid="preferences-full-answers"
            checked={display.show_full_answers === true}
            disabled={!displayLoaded || displaySaving}
            onChange={(event) =>
              void saveDisplay(
                { ...display, show_full_answers: event.target.checked },
                "Answer length saved.",
              )
            }
          />
          <span>Show full answers in a run (off shortens long ones behind a “Show more” button)</span>
        </label>
      </fieldset>

      <div className="account__actions">
        <Button
          type="button"
          variant="secondary"
          loading={saving}
          disabled={theme === DEFAULT_THEME}
          onClick={() => void reset()}
          data-testid="preferences-reset"
        >
          Reset to defaults
        </Button>
      </div>
    </section>
  );
}
