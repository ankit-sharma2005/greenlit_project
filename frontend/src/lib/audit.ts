/** Typed client for the append-only audit log (admin only). */

import { apiRequest } from "./api";

export interface AuditEvent {
  id: string;
  actor_id: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  event_metadata: Record<string, unknown>;
  ip_address: string | null;
  created_at: string;
}

export interface AuditList {
  items: AuditEvent[];
  total: number;
  limit: number;
  offset: number;
}

export interface AuditQuery {
  limit?: number;
  offset?: number;
  /** Case-insensitive substring of the action, e.g. "auth". */
  action?: string;
  targetType?: string;
}

export function listAuditEvents(query: AuditQuery = {}): Promise<AuditList> {
  const params = new URLSearchParams();
  params.set("limit", String(query.limit ?? 20));
  params.set("offset", String(query.offset ?? 0));
  if (query.action?.trim()) params.set("action", query.action.trim());
  if (query.targetType?.trim()) params.set("target_type", query.targetType.trim());
  return apiRequest(`/api/v1/audit?${params.toString()}`);
}
