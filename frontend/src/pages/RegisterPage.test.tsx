import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CurrentUser } from "../lib/authApi";
import { RegisterPage } from "./RegisterPage";

const mocks = vi.hoisted(() => ({ register: vi.fn() }));

vi.mock("../auth/authContext", () => ({
  useAuth: () => ({
    login: vi.fn(),
    register: mocks.register,
    logout: vi.fn(),
    user: null,
    status: "anonymous",
  }),
}));

const USER: CurrentUser = {
  id: "9f7f2c1a-0000-4000-8000-000000000000",
  email: "ada@example.com",
  name: "Ada",
  role: "admin",
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
};

function renderRegister() {
  return render(
    <MemoryRouter initialEntries={["/register"]}>
      <Routes>
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/" element={<div>Home page</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("RegisterPage", () => {
  beforeEach(() => {
    mocks.register.mockReset();
  });

  it("requires a password of at least ten characters", async () => {
    renderRegister();

    await userEvent.type(screen.getByLabelText("Name"), "Ada");
    await userEvent.type(screen.getByLabelText("Email"), "ada@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "short");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Use at least 10 characters for your password.",
    );
    expect(mocks.register).not.toHaveBeenCalled();
  });

  it("creates the account and goes home", async () => {
    mocks.register.mockResolvedValue(USER);
    renderRegister();

    await userEvent.type(screen.getByLabelText("Name"), "Ada");
    await userEvent.type(screen.getByLabelText("Email"), "ada@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "correct horse battery");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect(mocks.register).toHaveBeenCalledWith({
      name: "Ada",
      email: "ada@example.com",
      password: "correct horse battery",
    });
    expect(await screen.findByText("Home page")).toBeInTheDocument();
  });
});
