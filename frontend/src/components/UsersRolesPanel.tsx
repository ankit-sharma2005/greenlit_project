import { useCallback, useEffect, useState } from "react";

import { useAuth } from "../auth/authContext";
import { ApiError } from "../lib/api";
import { listUsers, ROLE_CHOICES, setUserRole, type AdminUser, type Role } from "../lib/adminUsers";
import { Button } from "./Button";
import "../styles/settings.css";

const PAGE_SIZE = 50;

/**
 * Settings → Users and roles: admin only.
 *
 * The server enforces every rule here (403 for everyone else, the last admin
 * cannot be demoted, an admin cannot change their own role); this panel only
 * offers the action and shows the answer. No password, hash or token is ever
 * requested or displayed.
 */
export function UsersRolesPanel() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [rows, setRows] = useState<AdminUser[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState("");
  const [appliedSearch, setAppliedSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pending, setPending] = useState<{ user: AdminUser; role: Role } | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (!isAdmin) return;
    setLoading(true);
    setError(null);
    try {
      const page = await listUsers({ search: appliedSearch, limit: PAGE_SIZE, offset });
      setRows(page.items);
      setTotal(page.total);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The account list could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, [appliedSearch, isAdmin, offset]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!isAdmin) {
    return (
      <p className="card__hint" data-testid="users-roles-forbidden">
        This needs the admin role. Ask an admin to change your role.
      </p>
    );
  }

  const confirmChange = async () => {
    if (!pending) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await setUserRole(pending.user.id, pending.role);
      setRows((current) => current.map((row) => (row.id === updated.id ? updated : row)));
      setNotice(`${updated.email} is now ${updated.role}.`);
      setPending(null);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The role could not be changed.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div data-testid="users-roles-panel">
      <p className="card__hint">
        Change what an account may do. Roles are admin, reviewer and member; every change is
        written to the audit log. To change your own role use the operator CLI.
      </p>

      <form
        className="settings__row"
        onSubmit={(event) => {
          event.preventDefault();
          setOffset(0);
          setAppliedSearch(search);
        }}
      >
        <label className="form__label" htmlFor="users-search">
          Search by email
        </label>
        <input
          id="users-search"
          data-testid="users-search"
          className="form__input"
          value={search}
          placeholder="part of an email"
          onChange={(event) => setSearch(event.target.value)}
        />
        <Button type="submit" variant="secondary">
          Search
        </Button>
      </form>

      {error ? (
        <p className="form-error" role="alert" data-testid="users-roles-error">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="card__hint" role="status" data-testid="users-roles-notice">
          {notice}
        </p>
      ) : null}
      {loading ? (
        <p className="card__hint" data-testid="users-roles-loading">
          Loading accounts…
        </p>
      ) : null}

      <table className="results__table" data-testid="users-roles-table">
        <thead>
          <tr>
            <th scope="col">Email</th>
            <th scope="col">Role</th>
            <th scope="col">Created</th>
            <th scope="col">Change</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const isSelf = row.id === user?.id;
            return (
              <tr key={row.id} data-testid={`users-row-${row.email}`}>
                <td>
                  {row.email}
                  {isSelf ? " (you)" : ""}
                </td>
                <td data-testid={`users-role-${row.email}`}>{row.role}</td>
                <td>{row.created_at.slice(0, 10)}</td>
                <td>
                  {isSelf ? (
                    <span className="card__hint">Your own role is changed with the CLI.</span>
                  ) : (
                    <select
                      className="form__input"
                      data-testid={`users-select-${row.email}`}
                      aria-label={`New role for ${row.email}`}
                      value={row.role}
                      onChange={(event) => {
                        const role = event.target.value as Role;
                        if (role !== row.role) setPending({ user: row, role });
                      }}
                    >
                      {ROLE_CHOICES.map((role) => (
                        <option key={role} value={role}>
                          {role}
                        </option>
                      ))}
                    </select>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {pending ? (
        <div className="card" data-testid="users-roles-confirm">
          <p>
            Change <strong>{pending.user.email}</strong> from {pending.user.role} to{" "}
            <strong>{pending.role}</strong>?
          </p>
          <div className="settings__row">
            <Button onClick={() => void confirmChange()} disabled={saving}>
              {saving ? "Saving…" : "Change role"}
            </Button>
            <Button variant="secondary" onClick={() => setPending(null)} disabled={saving}>
              Cancel
            </Button>
          </div>
        </div>
      ) : null}

      <div className="settings__row">
        <Button
          variant="secondary"
          onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          disabled={offset === 0 || loading}
        >
          Previous
        </Button>
        <span className="card__hint" data-testid="users-roles-count">
          {total} account{total === 1 ? "" : "s"}
        </span>
        <Button
          variant="secondary"
          onClick={() => setOffset(offset + PAGE_SIZE)}
          disabled={offset + PAGE_SIZE >= total || loading}
        >
          Next
        </Button>
      </div>
    </div>
  );
}
