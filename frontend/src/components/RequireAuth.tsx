import { Navigate, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "../auth/authContext";
import { isSessionExpired } from "../lib/session";
import { Spinner } from "./Spinner";

/** Blocks the app shell until the session check finishes, then requires a signed-in user. */
export function RequireAuth() {
  const { status } = useAuth();
  const location = useLocation();

  if (status === "loading") {
    return (
      <div className="splash" aria-busy="true">
        <Spinner size="xl" label="Checking your session" showLabel />
      </div>
    );
  }

  if (status === "anonymous") {
    return (
      <Navigate
        to="/login"
        replace
        state={{ from: location.pathname, sessionExpired: isSessionExpired() }}
      />
    );
  }

  return <Outlet />;
}
