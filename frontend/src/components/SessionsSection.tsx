import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "../auth/authContext";
import { ApiError } from "../lib/api";
import { formatDateTime } from "../lib/dates";
import { useAccountPreferences } from "../lib/useAccountPreferences";
import {
  fetchSessions,
  revokeOtherSessions,
  revokeSession,
  type SessionRow,
} from "../lib/sessions";
import { Button } from "./Button";

/**
 * The devices signed in to this account, one row per refresh-token family.
 *
 * The times are the API's: "started" is the family's first token and "last
 * activity" its newest, because the product keeps no last-used field — so nothing
 * here says "last seen online". Signing out the current device behaves like Sign
 * out; signing out the others keeps this one and asks first.
 */
export function SessionsSection() {
  const navigate = useNavigate();
  const { logout } = useAuth();
  const preferences = useAccountPreferences();
  const timeZone = preferences?.time_zone ?? null;
  const [rows, setRows] = useState<SessionRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    fetchSessions()
      .then((items) => {
        if (active) setRows(items);
      })
      .catch((caught: unknown) => {
        if (!active) return;
        setRows([]);
        setError(
          caught instanceof ApiError
            ? caught.message
            : "Could not load your sessions. Check your connection and try again.",
        );
      });
    return () => {
      active = false;
    };
  }, [reloadKey]);

  async function handleRevoke(row: SessionRow) {
    setBusy(row.id);
    setError(null);
    setNotice(null);
    try {
      const message = await revokeSession(row.id);
      if (row.current) {
        // Revoking the session you are using is a sign-out; let the app know.
        await logout().catch(() => undefined);
        navigate("/login", { replace: true });
        return;
      }
      setNotice(message);
      setReloadKey((key) => key + 1);
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "Could not sign that device out. Check your connection and try again.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function handleRevokeOthers() {
    setBusy("others");
    setError(null);
    setNotice(null);
    try {
      const revoked = await revokeOtherSessions();
      setConfirming(false);
      setNotice(
        revoked === 0
          ? "No other device was signed in."
          : revoked === 1
            ? "Signed out 1 other device."
            : `Signed out ${revoked} other devices.`,
      );
      setReloadKey((key) => key + 1);
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "Could not sign the other devices out. Check your connection and try again.",
      );
    } finally {
      setBusy(null);
    }
  }

  const others = (rows ?? []).filter((row) => !row.current);

  return (
    <div className="account__sessions" data-testid="account-sessions">
      {error ? (
        <p className="form-error" role="alert" data-testid="sessions-error">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="notice" role="status" data-testid="sessions-notice">
          {notice}
        </p>
      ) : null}

      {rows === null ? (
        <p className="card__hint" data-testid="sessions-loading">
          Loading your sessions…
        </p>
      ) : rows.length === 0 ? (
        <p className="card__hint" data-testid="sessions-empty">
          No other device is signed in to this account.
        </p>
      ) : (
        <ul className="account__session-list">
          {rows.map((row) => (
            <li
              key={row.id}
              className="account__session"
              data-testid="session-row"
              data-current={row.current ? "true" : "false"}
            >
              <div className="account__session-main">
                <span className="account__session-device" data-testid="session-device">
                  {row.device}
                </span>
                {row.current ? (
                  <span className="badge badge--go" data-testid="session-current">
                    This device
                  </span>
                ) : null}
                <span className="account__session-time">
                  Last activity{" "}
                  <time dateTime={row.last_activity} data-testid="session-last-activity">
                    {formatDateTime(row.last_activity, timeZone)}
                  </time>
                </span>
              </div>
              <Button
                type="button"
                variant="secondary"
                loading={busy === row.id}
                loadingLabel="Signing out this device"
                disabled={busy !== null}
                onClick={() => void handleRevoke(row)}
                data-testid="session-revoke"
              >
                Sign out this device
              </Button>
            </li>
          ))}
        </ul>
      )}

      {others.length > 0 ? (
        confirming ? (
          <div className="account__actions" data-testid="session-confirm">
            <p className="card__hint">
              Sign out {others.length === 1 ? "1 other device" : `${others.length} other devices`}?
              This device stays signed in.
            </p>
            <Button
              type="button"
              variant="primary"
              loading={busy === "others"}
              loadingLabel="Signing the other devices out"
              onClick={() => void handleRevokeOthers()}
              data-testid="session-revoke-others-confirm"
            >
              Yes, sign the others out
            </Button>
            <Button
              type="button"
              variant="secondary"
              disabled={busy !== null}
              onClick={() => setConfirming(false)}
              data-testid="session-revoke-others-cancel"
            >
              Cancel
            </Button>
          </div>
        ) : (
          <Button
            type="button"
            variant="secondary"
            disabled={busy !== null}
            onClick={() => setConfirming(true)}
            data-testid="session-revoke-others"
          >
            Sign out all other devices
          </Button>
        )
      ) : null}
    </div>
  );
}
