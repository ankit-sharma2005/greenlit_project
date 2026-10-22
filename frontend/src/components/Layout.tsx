import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";

import { Brand } from "./Brand";

type Theme = "dark" | "light";

const THEME_STORAGE_KEY = "greenlit-theme";

const NAV_ITEMS = [
  { to: "/", label: "New Test", end: true },
  { to: "/results", label: "Results", end: false },
  { to: "/test-chat", label: "Test Chat", end: false },
  { to: "/settings", label: "Settings", end: false },
];

function readStoredTheme(): Theme {
  try {
    return window.localStorage.getItem(THEME_STORAGE_KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

export function Layout() {
  const [theme, setTheme] = useState<Theme>(readStoredTheme);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch {
      // Storage can be unavailable (private mode); the theme still applies for the session.
    }
  }, [theme]);

  const nextTheme: Theme = theme === "dark" ? "light" : "dark";

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="Main navigation">
        <Brand />
        <nav className="sidebar__nav">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                isActive ? "sidebar__link sidebar__link--active" : "sidebar__link"
              }
            >
              {item.label}
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
            onClick={() => setTheme(nextTheme)}
            aria-label={`Switch to ${nextTheme} theme`}
          >
            {theme === "dark" ? "Light theme" : "Dark theme"}
          </button>

          <span className="health-badge" title="Accounts arrive in the next milestone.">
            Guest
          </span>
        </header>

        <main className="page">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
