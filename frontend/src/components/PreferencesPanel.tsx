import { useState } from "react";

import { DEFAULT_THEME, THEME_OPTIONS, type Theme } from "../lib/theme";
import { useTheme } from "../theme/themeContext";
import { Button } from "./Button";
import "../styles/settings.css";

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
