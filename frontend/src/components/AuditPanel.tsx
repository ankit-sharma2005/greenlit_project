import { useCallback, useEffect, useState } from "react";

import { Button } from "./Button";
import { ApiError } from "../lib/api";
import { listAuditEvents, type AuditEvent } from "../lib/audit";
import "../styles/results.css";

const PAGE_SIZE = 20;
const TARGET_TYPES = ["", "run", "dataset", "provider", "user", "run_item"];

/**
 * The append-only audit log (admin only): what happened, to what, by whom.
 *
 * The table pages and filters on the server, so the log stays usable once it is
 * long; a non-admin gets the API's 403 message rather than an empty table.
 */
export function AuditPanel() {
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [action, setAction] = useState("");
  const [targetType, setTargetType] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const page = await listAuditEvents({ limit: PAGE_SIZE, offset, action, targetType });
      setEvents(page.items);
      setTotal(page.total);
      setError(null);
    } catch (caught) {
      setEvents([]);
      setError(
        caught instanceof ApiError
          ? caught.message
          : "Could not read the audit log. Check that the API is running.",
      );
    }
  }, [action, offset, targetType]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section data-testid="audit-panel">
      <div className="form__row" style={{ display: "flex", gap: "var(--space-3)" }}>
        <label className="sr-only" htmlFor="audit-action">
          Filter by action
        </label>
        <input
          id="audit-action"
          type="search"
          placeholder="Filter by action, e.g. auth"
          value={action}
          onChange={(event) => {
            setOffset(0);
            setAction(event.target.value);
          }}
          data-testid="audit-action-filter"
        />
        <label className="sr-only" htmlFor="audit-target">
          Filter by target type
        </label>
        <select
          id="audit-target"
          value={targetType}
          onChange={(event) => {
            setOffset(0);
            setTargetType(event.target.value);
          }}
          data-testid="audit-target-filter"
        >
          {TARGET_TYPES.map((value) => (
            <option key={value || "all"} value={value}>
              {value || "Every target"}
            </option>
          ))}
        </select>
      </div>

      {error ? (
        <p className="form-error" role="alert" data-testid="audit-error">
          {error}
        </p>
      ) : null}

      {events === null ? (
        <p className="card__hint" data-testid="audit-loading">
          Reading the audit log…
        </p>
      ) : events.length === 0 ? (
        <p className="card__hint" data-testid="audit-empty">
          No audit events match this filter.
        </p>
      ) : (
        <table className="results__table" data-testid="audit-table">
          <thead>
            <tr>
              <th scope="col">When</th>
              <th scope="col">Action</th>
              <th scope="col">Target</th>
              <th scope="col">Actor</th>
              <th scope="col">Details</th>
            </tr>
          </thead>
          <tbody>
            {events.map((event) => (
              <tr key={event.id} data-testid="audit-row">
                <td>{new Date(event.created_at).toLocaleString()}</td>
                <td>{event.action}</td>
                <td>{[event.target_type, event.target_id].filter(Boolean).join(" ") || "—"}</td>
                <td>{event.actor_id ?? "system"}</td>
                <td>
                  <code>{JSON.stringify(event.event_metadata)}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div style={{ display: "flex", gap: "var(--space-3)", alignItems: "center" }}>
        <Button
          variant="secondary"
          onClick={() => setOffset((current) => Math.max(0, current - PAGE_SIZE))}
          disabled={offset === 0}
          data-testid="audit-prev"
        >
          Previous
        </Button>
        <Button
          variant="secondary"
          onClick={() => setOffset((current) => current + PAGE_SIZE)}
          disabled={offset + PAGE_SIZE >= total}
          data-testid="audit-next"
        >
          Next
        </Button>
        <span className="card__hint" data-testid="audit-range">
          {total === 0
            ? "0 events"
            : `${offset + 1}–${Math.min(offset + PAGE_SIZE, total)} of ${total}`}
        </span>
      </div>
    </section>
  );
}
