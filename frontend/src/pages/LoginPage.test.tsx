import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../lib/api";
import type { CurrentUser } from "../lib/authApi";
import { LoginPage } from "./LoginPage";

const mocks = vi.hoisted(() => ({ login: vi.fn() }));

vi.mock("../auth/authContext", () => ({
  useAuth: () => ({
    login: mocks.login,
    register: vi.fn(),
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

function renderLogin() {
  return render(
    <MemoryRouter initialEntries={["/login"]}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<div>Home page</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("LoginPage", () => {
  beforeEach(() => {
    mocks.login.mockReset();
  });

  it("shows the brand and both fields", () => {
    renderLogin();

    expect(screen.getByRole("link", { name: "GreenLit home" })).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
  });

  it("signs in and redirects home", async () => {
    mocks.login.mockResolvedValue(USER);
    renderLogin();

    await userEvent.type(screen.getByLabelText("Email"), "ada@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "correct horse battery");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(mocks.login).toHaveBeenCalledWith("ada@example.com", "correct horse battery");
    expect(await screen.findByText("Home page")).toBeInTheDocument();
  });

  it("shows the server's message and re-enables the button on failure", async () => {
    mocks.login.mockRejectedValue(new ApiError("Email or password is incorrect.", 401));
    renderLogin();

    await userEvent.type(screen.getByLabelText("Email"), "ada@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "wrong password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Email or password is incorrect.");
    expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();
  });

  it("validates empty fields without calling the API", async () => {
    renderLogin();

    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(screen.getByRole("alert")).toHaveTextContent("Enter your email and password.");
    expect(mocks.login).not.toHaveBeenCalled();
  });

  it("shows the spinner while the request is in flight", async () => {
    let resolveLogin: (user: CurrentUser) => void = () => undefined;
    mocks.login.mockReturnValue(
      new Promise<CurrentUser>((resolve) => {
        resolveLogin = resolve;
      }),
    );
    renderLogin();

    await userEvent.type(screen.getByLabelText("Email"), "ada@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "correct horse battery");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(screen.getByRole("status")).toBeInTheDocument());
    expect(screen.getByRole("status")).toHaveTextContent("Signing in");

    await act(async () => {
      resolveLogin(USER);
    });

    expect(await screen.findByText("Home page")).toBeInTheDocument();
  });
});
