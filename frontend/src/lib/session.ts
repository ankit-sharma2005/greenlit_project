/**
 * Silent session refresh (D1.2 continues here).
 *
 * The access cookie lives 15 minutes and the refresh cookie 14 days, so a 401
 * usually means "the access token aged out", not "signed out". Refresh tokens
 * ROTATE and reusing one revokes the whole family (theft detection), so every
 * concurrent caller must share one refresh: `refreshSession` is single-flight
 * in this tab, and a Web Lock keeps two tabs from refreshing at the same time.
 */

export type RefreshOutcome = "ok" | "expired" | "error";

/** Mirrors `API_BASE_URL` in `api.ts`; kept here so the two modules do not import each other. */
const BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8003";

const SESSION_EXPIRED_EVENT = "greenlit:session-expired";
const REFRESH_LOCK = "greenlit-refresh";

let inFlight: Promise<RefreshOutcome> | null = null;
let expired = false;

/** True once a refresh proved the session is over (not for network/5xx trouble). */
export function isSessionExpired(): boolean {
  return expired;
}

export function resetSessionExpired(): void {
  expired = false;
}

function markExpired(): void {
  expired = true;
  window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
}

/** Subscribe to "the session is really over"; returns the unsubscribe function. */
export function onSessionExpired(handler: () => void): () => void {
  window.addEventListener(SESSION_EXPIRED_EVENT, handler);
  return () => window.removeEventListener(SESSION_EXPIRED_EVENT, handler);
}

async function callRefresh(): Promise<RefreshOutcome> {
  try {
    const response = await fetch(`${BASE_URL}/api/v1/auth/refresh`, {
      method: "POST",
      credentials: "include",
    });
    if (response.ok) {
      resetSessionExpired();
      return "ok";
    }
    if (response.status === 401 || response.status === 403) {
      // The refresh cookie is gone, revoked or the family was killed: really signed out.
      markExpired();
      return "expired";
    }
    // A 5xx says nothing about the session: keep the user signed in and let the
    // original error surface.
    return "error";
  } catch {
    return "error";
  }
}

/** Run the refresh under the Web Lock when the browser has it; fall back otherwise. */
async function withCrossTabLock(task: () => Promise<RefreshOutcome>): Promise<RefreshOutcome> {
  const locks = (navigator as Navigator & { locks?: LockManager }).locks;
  if (typeof locks?.request !== "function") {
    return task();
  }
  try {
    return await locks.request(REFRESH_LOCK, task);
  } catch {
    // A denied or unavailable lock must not break signing in: refresh anyway.
    return task();
  }
}

/**
 * Refresh once, shared by every concurrent caller in this tab.
 *
 * Inside the lock the cookie may already be the new one another tab wrote, so a
 * second refresh rotates it again instead of presenting a revoked token.
 */
export function refreshSession(): Promise<RefreshOutcome> {
  if (inFlight) return inFlight;
  inFlight = withCrossTabLock(callRefresh).finally(() => {
    inFlight = null;
  });
  return inFlight;
}

/** Test-only: forget an in-flight refresh so each test starts clean. */
export function resetRefreshState(): void {
  inFlight = null;
  expired = false;
}
