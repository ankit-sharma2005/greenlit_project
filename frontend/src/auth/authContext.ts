import { createContext, useContext } from "react";

import type { CurrentUser, ProfileUpdatePayload, RegisterPayload } from "../lib/authApi";

export type AuthStatus = "loading" | "authenticated" | "anonymous";

export interface AuthContextValue {
  user: CurrentUser | null;
  status: AuthStatus;
  login: (email: string, password: string) => Promise<CurrentUser>;
  register: (payload: RegisterPayload) => Promise<CurrentUser>;
  logout: () => Promise<void>;
  /** Save a display-name change and update the shared user, so the topbar follows. */
  updateProfile: (payload: ProfileUpdatePayload) => Promise<CurrentUser>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside <AuthProvider>");
  }
  return context;
}
