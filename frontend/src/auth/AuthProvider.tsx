import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { ApiError } from "../lib/api";
import {
  fetchCurrentUser,
  loginRequest,
  logoutRequest,
  registerRequest,
  updateProfileRequest,
  type CurrentUser,
  type ProfileUpdatePayload,
  type RegisterPayload,
} from "../lib/authApi";
import { onSessionExpired, resetSessionExpired } from "../lib/session";
import { AuthContext, type AuthContextValue, type AuthStatus } from "./authContext";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");

  useEffect(() => {
    const unsubscribe = onSessionExpired(() => {
      setUser(null);
      setStatus("anonymous");
    });
    return unsubscribe;
  }, []);

  useEffect(() => {
    let cancelled = false;

    fetchCurrentUser()
      .then((current) => {
        if (!cancelled) {
          setUser(current);
          setStatus("authenticated");
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          // A 401 simply means "signed out"; network errors must not block the sign-in form.
          if (!(error instanceof ApiError) || error.status !== 401) {
            console.warn("Could not check the session:", error);
          }
          setUser(null);
          setStatus("anonymous");
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    resetSessionExpired();
    const result = await loginRequest(email, password);
    setUser(result.user);
    setStatus("authenticated");
    return result.user;
  }, []);

  const register = useCallback(async (payload: RegisterPayload) => {
    resetSessionExpired();
    const result = await registerRequest(payload);
    setUser(result.user);
    setStatus("authenticated");
    return result.user;
  }, []);

  const logout = useCallback(async () => {
    resetSessionExpired();
    try {
      await logoutRequest();
    } finally {
      setUser(null);
      setStatus("anonymous");
    }
  }, []);

  const updateProfile = useCallback(async (payload: ProfileUpdatePayload) => {
    const updated = await updateProfileRequest(payload);
    setUser(updated);
    return updated;
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ user, status, login, register, logout, updateProfile }),
    [user, status, login, register, logout, updateProfile],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
