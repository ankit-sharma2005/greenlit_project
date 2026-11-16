/** Typed client for admin user management (Settings → Users and roles). */

import { apiRequest } from "./api";

export type Role = "admin" | "member" | "reviewer";

export interface AdminUser {
  id: string;
  email: string;
  name: string;
  role: Role;
  is_active: boolean;
  created_at: string;
}

export interface AdminUserPage {
  items: AdminUser[];
  total: number;
  limit: number;
  offset: number;
}

export const ROLE_CHOICES: Role[] = ["member", "reviewer", "admin"];

/** One page of accounts, optionally filtered by a piece of the email. */
export async function listUsers(
  options: { search?: string; limit?: number; offset?: number } = {},
): Promise<AdminUserPage> {
  const params = new URLSearchParams();
  params.set("limit", String(options.limit ?? 50));
  params.set("offset", String(options.offset ?? 0));
  if (options.search?.trim()) params.set("search", options.search.trim());
  return apiRequest<AdminUserPage>(`/api/v1/users?${params.toString()}`);
}

/** Change another account's role. The server refuses the last admin and yourself. */
export async function setUserRole(userId: string, role: Role): Promise<AdminUser> {
  return apiRequest<AdminUser>(`/api/v1/users/${userId}/role`, {
    method: "PATCH",
    body: { role },
  });
}
