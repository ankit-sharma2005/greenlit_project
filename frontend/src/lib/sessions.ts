import { apiRequest } from "./api";

/**
 * One signed-in device. The API sends a family id, a label built from the stored
 * user agent, when the session started and its last activity — never a token, a
 * hash or an IP address.
 *
 * "Last activity" is the newest refresh token's creation time: the product has no
 * last-used column, so it is not "last seen online" and the UI must not call it that.
 */
export interface SessionRow {
  id: string;
  device: string;
  created_at: string;
  last_activity: string;
  current: boolean;
}

interface SessionsResponse {
  items: SessionRow[];
  total: number;
}

export async function fetchSessions(): Promise<SessionRow[]> {
  const body = await apiRequest<SessionsResponse>("/api/v1/auth/sessions");
  return body.items;
}

/** Sign out one device; returns the API's own sentence for the notice. */
export async function revokeSession(id: string): Promise<string> {
  const body = await apiRequest<{ message: string }>(
    `/api/v1/auth/sessions/${encodeURIComponent(id)}/revoke`,
    { method: "POST" },
  );
  return body.message;
}

/** Sign out every other device; returns how many were signed out. */
export async function revokeOtherSessions(): Promise<number> {
  const body = await apiRequest<{ revoked: number }>("/api/v1/auth/sessions/revoke-others", {
    method: "POST",
  });
  return body.revoked;
}
