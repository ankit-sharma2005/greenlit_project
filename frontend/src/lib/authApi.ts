import { apiRequest } from "./api";

export type Role = "admin" | "member" | "reviewer";

export interface CurrentUser {
  id: string;
  email: string;
  name: string;
  role: Role;
  is_active: boolean;
  created_at: string;
}

interface AuthResponse {
  user: CurrentUser;
}

export interface RegisterPayload {
  name: string;
  email: string;
  password: string;
}

export function loginRequest(email: string, password: string): Promise<AuthResponse> {
  return apiRequest<AuthResponse>("/api/v1/auth/login", {
    method: "POST",
    body: { email, password },
  });
}

export function registerRequest(payload: RegisterPayload): Promise<AuthResponse> {
  return apiRequest<AuthResponse>("/api/v1/auth/register", {
    method: "POST",
    body: payload,
  });
}

export function logoutRequest(): Promise<{ message: string }> {
  return apiRequest<{ message: string }>("/api/v1/auth/logout", { method: "POST" });
}

export function fetchCurrentUser(): Promise<CurrentUser> {
  return apiRequest<CurrentUser>("/api/v1/auth/me");
}
