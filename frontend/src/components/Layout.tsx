import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/authContext";
import { useTheme } from "../theme/themeContext";
import { Brand } from "./Brand";
import { Button } from "./Button";

const NAV_ITEMS = [
  { to: "/", label: "New Test", end: true },
  { to: "/results", label: "Results", end: false },
  { to: "/calibration", label: "Calibration", end: false },
  { to: "/test-chat", label: "Test Chat", end: false },
  { to: "/settings", label: "Settings", end: false },
];

/** Where the rail preference lives; a blocked storage just means "expanded". */
export const SIDEBAR_STORAGE_KEY = "greenlit-sidebar-collapsed";

/** Read before the first render, so the rail never flashes open then shut. */
function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(SIDEBAR_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

function storeCollapsed(collapsed: boolean): void {
  try {
    window.localStorage.setItem(SIDEBAR_STORAGE_KEY, String(collapsed));
  } catch {
    // Navigation must keep working when storage is blocked or full.
  }
}

export function Layout() {
  const { user, logout } = useAuth();
  const { resolved, setTheme } = useTheme();
  const navigate = useNavigate();
  const [signingOut, setSigningOut] = useState(false);
  // Desktop only: the mobile strip stays as it is (it fits at 375px).
  const [collapsed, setCollapsed] = useState(readCollapsed);

  // The toggle flips whatever is on screen, including when "system" chose it.
  const nextTheme = resolved === "dark" ? "light" : "dark";

  async function handleSignOut() {
    setSigningOut(true);
    try {
      await logout();
      navigate("/login", { replace: true });
    } finally {
      setSigningOut(false);
    }
  }

  function toggleSidebar() {
    const next = !collapsed;
    setCollapsed(next);
    storeCollapsed(next);
  }

  return (
    <div className={collapsed ? "app-shell app-shell--collapsed" : "app-shell"}>
      <aside
        className="sidebar"
        aria-label="Main navigation"
        data-testid={collapsed ? "sidebar-rail" : undefined}
      >
        <div className="sidebar__head">
          <Brand />
          <button
            type="button"
            className="sidebar__toggle"
            data-testid="sidebar-toggle"
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-expanded={!collapsed}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            onClick={toggleSidebar}
          >
            <span className="sidebar__toggle-glyph" aria-hidden="true">
              {collapsed ? "\u203a" : "\u2039"}
            </span>
          </button>
        </div>
        <nav className="sidebar__nav">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              title={item.label}
              className={({ isActive }) =>
                isActive ? "sidebar__link sidebar__link--active" : "sidebar__link"
              }
            >
              <span className="sidebar__link-mark" aria-hidden="true">
                {item.label.charAt(0)}
              </span>
              <span className="sidebar__link-label">{item.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar__footer">
          <span>GreenLit v0.1.0</span>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <label className="sr-only" htmlFor="project-select">
            Active project
          </label>
          <select
            id="project-select"
            className="topbar__project"
            defaultValue="default"
            disabled
            title="Project switching is coming soon."
          >
            <option value="default">Default project</option>
          </select>

          <span className="health-badge" title="Provider checks arrive in the next milestone.">
            <span className="status-dot" aria-hidden="true" />
            Provider unknown
          </span>

          <div className="topbar__spacer" />

          <button
            type="button"
            className="btn btn--secondary topbar__theme"
            onClick={() => void setTheme(nextTheme)}
            aria-label={`Switch to ${nextTheme} theme`}
          >
            {resolved === "dark" ? "Light theme" : "Dark theme"}
          </button>

          {user ? (
            <span className="user-menu">
              <span className="badge" data-testid="user-role" title={`Signed in as ${user.role}`}>
                {user.role}
              </span>
              <span className="user-menu__name">
                <strong>{user.name}</strong>
                <span className="user-menu__email">{user.email}</span>
              </span>
              <Button
                variant="ghost"
                onClick={handleSignOut}
                loading={signingOut}
                loadingLabel="Signing out"
              >
                Sign out
              </Button>
            </span>
          ) : null}
        </header>

        <main className="page">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
