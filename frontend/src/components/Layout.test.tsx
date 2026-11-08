import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Layout, SIDEBAR_STORAGE_KEY } from "./Layout";

vi.mock("../auth/authContext", () => ({
  useAuth: () => ({
    user: { id: "u1", name: "Ada", email: "ada@example.com", role: "admin" },
    status: "authenticated",
    logout: vi.fn(),
  }),
}));

vi.mock("../theme/themeContext", () => ({
  useTheme: () => ({ theme: "dark", resolved: "dark", saving: false, error: null, setTheme: vi.fn() }),
}));

/** The navigation the sidebar has always had: labels, order and targets. */
const NAV = [
  { label: "New Test", href: "/" },
  { label: "Results", href: "/results" },
  { label: "Calibration", href: "/calibration" },
  { label: "Test Chat", href: "/test-chat" },
  { label: "Settings", href: "/settings" },
];

function renderLayout() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<p>New Test page</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

function navLinks() {
  const nav = screen.getByRole("navigation");
  return {
    labels: [...nav.querySelectorAll(".sidebar__link-label")].map((span) => span.textContent),
    links: within(nav).getAllByRole("link"),
  };
}

describe("Layout sidebar", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("keeps the same navigation labels, order, hrefs and titles", () => {
    renderLayout();

    const { labels, links } = navLinks();
    expect(labels).toEqual(NAV.map((item) => item.label));
    expect(links.map((link) => link.getAttribute("href"))).toEqual(NAV.map((item) => item.href));
    expect(links.map((link) => link.getAttribute("title"))).toEqual(NAV.map((item) => item.label));
  });

  it("collapses to a rail, reports it, and expands again", async () => {
    const user = userEvent.setup();
    renderLayout();

    const toggle = screen.getByTestId("sidebar-toggle");
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(toggle).toHaveAccessibleName("Collapse sidebar");
    expect(document.querySelector(".app-shell")).not.toHaveClass("app-shell--collapsed");

    await user.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveAccessibleName("Expand sidebar");
    expect(document.querySelector(".app-shell")).toHaveClass("app-shell--collapsed");
    expect(screen.getByTestId("sidebar-rail")).toBeInTheDocument();
    expect(window.localStorage.getItem(SIDEBAR_STORAGE_KEY)).toBe("true");

    await user.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.queryByTestId("sidebar-rail")).not.toBeInTheDocument();
    expect(window.localStorage.getItem(SIDEBAR_STORAGE_KEY)).toBe("false");
  });

  it("folds and unfolds from the keyboard", async () => {
    const user = userEvent.setup();
    renderLayout();

    const toggle = screen.getByTestId("sidebar-toggle");
    toggle.focus();
    expect(toggle).toHaveFocus();

    await user.keyboard("{Enter}");
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    await user.keyboard(" ");
    expect(toggle).toHaveAttribute("aria-expanded", "true");
  });

  it("restores a stored rail state on the first render", () => {
    window.localStorage.setItem(SIDEBAR_STORAGE_KEY, "true");

    renderLayout();

    expect(screen.getByTestId("sidebar-toggle")).toHaveAttribute("aria-expanded", "false");
    expect(document.querySelector(".app-shell")).toHaveClass("app-shell--collapsed");
  });

  it("starts expanded and keeps working when storage throws", async () => {
    const getItem = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("storage blocked");
    });
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("storage blocked");
    });
    const user = userEvent.setup();

    renderLayout();

    const toggle = screen.getByTestId("sidebar-toggle");
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    await user.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "false");

    getItem.mockRestore();
    setItem.mockRestore();
  });
});
