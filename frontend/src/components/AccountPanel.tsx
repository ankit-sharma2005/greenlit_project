import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "../auth/authContext";
import { ApiError } from "../lib/api";
import { formatDate as formatInZone } from "../lib/dates";
import { useAccountPreferences } from "../lib/useAccountPreferences";
import { Button } from "./Button";
import "../styles/settings.css";

const MAX_NAME_LENGTH = 120;

function formatDate(value: string, timeZone?: string | null): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown";
  // The zone comes from the account; with none chosen this is the browser's own.
  return formatInZone(value, timeZone);
}

/**
 * Settings → Account: the profile the API knows, a display-name edit that is
 * scoped to the signed-in user, and sign-out.
 *
 * Everything shown comes from `/auth/me`; nothing is inferred. A password is
 * never displayed or offered here (resets are the existing API-only flow), and
 * account deletion is not offered because the backend has no safe cascade for
 * it yet.
 */
export function AccountPanel() {
  const { user, logout, updateProfile } = useAuth();
  const navigate = useNavigate();
  const [name, setName] = useState(user?.name ?? "");
  const [saving, setSaving] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // The creation date is shown in the account's chosen zone, when there is one.
  const preferences = useAccountPreferences();
  const timeZone = preferences?.time_zone ?? null;

  // Keep the field in step when the shared user changes (a save, or a refresh).
  useEffect(() => {
    setName(user?.name ?? "");
  }, [user?.name]);

  if (!user) {
    return (
      <section className="card" data-testid="account-panel">
        <div className="card__header">
          <h2>Account</h2>
        </div>
        <p className="form-error" role="alert" data-testid="account-unavailable">
          Your account information is unavailable. Reload the page; if this persists, sign in again.
        </p>
      </section>
    );
  }

  const trimmed = name.trim();
  const dirty = trimmed.length > 0 && trimmed !== user.name;

  async function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setNotice(null);

    if (!trimmed) {
      setError("Enter a display name.");
      return;
    }

    setSaving(true);
    try {
      const updated = await updateProfile({ name: trimmed });
      setName(updated.name);
      setNotice("Display name saved.");
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "Could not save your display name. Check your connection and try again.",
      );
    } finally {
      setSaving(false);
    }
  }

  async function handleSignOut() {
    setSigningOut(true);
    try {
      await logout();
      navigate("/login", { replace: true });
    } finally {
      setSigningOut(false);
    }
  }

  return (
    <section className="card" aria-labelledby="account-heading" data-testid="account-panel">
      <div className="card__header">
        <h2 id="account-heading">Account</h2>
        <span
          className={user.is_active ? "badge badge--go" : "badge badge--review"}
          data-testid="account-status"
        >
          {user.is_active ? "Active" : "Inactive"}
        </span>
      </div>
      <p className="card__hint">
        Your profile as the API records it. The display name appears in the topbar and in audit
        entries; your email is the sign-in identity and cannot be changed here.
      </p>

      {error ? (
        <p className="form-error" role="alert" data-testid="account-error">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="notice" role="status" data-testid="account-notice">
          {notice}
        </p>
      ) : null}

      <dl className="account__details">
        <div>
          <dt>Display name</dt>
          <dd data-testid="account-name-value">{user.name}</dd>
        </div>
        <div>
          <dt>Email</dt>
          <dd data-testid="account-email">{user.email}</dd>
        </div>
        <div>
          <dt>Role</dt>
          <dd data-testid="account-role">{user.role}</dd>
        </div>
        <div>
          <dt>Account status</dt>
          <dd data-testid="account-active">{user.is_active ? "Active" : "Inactive"}</dd>
        </div>
        <div>
          <dt>Member since</dt>
          <dd data-testid="account-created">{formatDate(user.created_at, timeZone)}</dd>
        </div>
        <div>
          <dt>Account ID</dt>
          <dd>
            <code data-testid="account-id">{user.id}</code>
          </dd>
        </div>
      </dl>

      <h3 className="account__heading">Edit display name</h3>
      <form className="account__form" onSubmit={(event) => void handleSave(event)} noValidate>
        <div className="settings-field">
          <label htmlFor="account-name">Display name</label>
          <input
            id="account-name"
            data-testid="account-name"
            value={name}
            maxLength={MAX_NAME_LENGTH}
            autoComplete="name"
            disabled={saving}
            onChange={(event) => setName(event.target.value)}
          />
          <p className="card__hint">Up to {MAX_NAME_LENGTH} characters. Blank names are refused.</p>
        </div>
        <div className="account__actions">
          <Button
            type="submit"
            variant="primary"
            loading={saving}
            loadingLabel="Saving display name"
            disabled={!dirty}
            data-testid="account-save"
          >
            Save display name
          </Button>
          {name !== user.name ? (
            <Button
              type="button"
              variant="secondary"
              disabled={saving}
              onClick={() => setName(user.name)}
              data-testid="account-cancel"
            >
              Cancel
            </Button>
          ) : null}
        </div>
      </form>

      <h3 className="account__heading">Session</h3>
      <p className="card__hint">
        Signing out revokes this browser&apos;s refresh token, so the session cannot be resumed.
      </p>
      <Button
        type="button"
        variant="secondary"
        onClick={() => void handleSignOut()}
        loading={signingOut}
        loadingLabel="Signing out"
        data-testid="account-sign-out"
      >
        Sign out
      </Button>

      <h3 className="account__heading">Not available here</h3>
      <ul className="account__notes">
        <li>
          <strong>Password change:</strong> GreenLit has no in-app password form. Resets use{" "}
          <code>POST /api/v1/auth/password-reset/request</code>, which currently needs an email
          provider that is not wired up, so the token is returned only in development.
        </li>
        <li>
          <strong>Account deletion:</strong> not offered. Deleting an account would cascade to
          datasets, runs and audit history, and no safe confirmation flow exists yet.
        </li>
      </ul>
    </section>
  );
}
