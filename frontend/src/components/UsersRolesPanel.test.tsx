import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { UsersRolesPanel } from "./UsersRolesPanel";
import { AuthContext, type AuthContextValue } from "../auth/authContext";
import { ApiError } from "../lib/api";
import type { AdminUser, AdminUserPage } from "../lib/adminUsers";
import type { CurrentUser } from "../lib/authApi";

vi.mock("../lib/adminUsers", async () => {
  const actual = await vi.importActual<typeof import("../lib/adminUsers")>("../lib/adminUsers");
  return {
    ...actual,
    listUsers: vi.fn(),
    setUserRole: vi.fn(),
  };
});

const { listUsers, setUserRole } = await import("../lib/adminUsers");
const mockedList = vi.mocked(listUsers);
const mockedSet = vi.mocked(setUserRole);

const admin: CurrentUser = {
  id: "11111111-1111-4111-8111-111111111111",
  email: "admin@example.com",
  name: "Admin",
  role: "admin",
  is_active: true,
  created_at: "2026-01-02T03:04:05Z",
};

const memberUser: AdminUser = {
  id: "22222222-2222-4222-8222-222222222222",
  email: "member@example.com",
  name: "Member",
  role: "member",
  is_active: true,
  created_at: "2026-02-03T04:05:06Z",
};

const page: AdminUserPage = {
  items: [
    {
      id: admin.id,
      email: "admin@example.com",
      name: "Admin",
      role: "admin",
      is_active: true,
      created_at: "2026-01-02T03:04:05Z",
    },
    memberUser,
  ],
  total: 2,
  limit: 50,
  offset: 0,
};

function renderPanel(user: CurrentUser = admin): void {
  const value: AuthContextValue = {
    user,
    status: "authenticated",
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn().mockResolvedValue(undefined),
    updateProfile: vi.fn().mockResolvedValue(user),
  };
  render(
    <AuthContext.Provider value={value}>
      <UsersRolesPanel />
    </AuthContext.Provider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedList.mockResolvedValue(page);
  mockedSet.mockResolvedValue({ ...memberUser, role: "reviewer" });
});

describe("UsersRolesPanel", () => {
  it("shows the accounts to an admin and never their own controls", async () => {
    renderPanel();
    expect(await screen.findByTestId("users-row-member@example.com")).toBeInTheDocument();
    expect(screen.getByTestId("users-role-member@example.com")).toHaveTextContent("member");
    expect(screen.getByTestId("users-row-admin@example.com")).toHaveTextContent("(you)");
    expect(screen.queryByTestId("users-select-admin@example.com")).not.toBeInTheDocument();
    expect(screen.getByTestId("users-roles-count")).toHaveTextContent("2 accounts");
  });

  it("asks for confirmation and then changes the role", async () => {
    renderPanel();
    const select = await screen.findByTestId("users-select-member@example.com");
    await userEvent.selectOptions(select, "reviewer");

    expect(screen.getByTestId("users-roles-confirm")).toHaveTextContent("member@example.com");
    expect(mockedSet).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Change role" }));
    const memberId = memberUser.id;
    await waitFor(() => expect(mockedSet).toHaveBeenCalledWith(memberId, "reviewer"));
    expect(await screen.findByTestId("users-role-member@example.com")).toHaveTextContent(
      "reviewer",
    );
    expect(screen.getByTestId("users-roles-notice")).toHaveTextContent("is now reviewer");
  });

  it("shows the server's refusal instead of pretending it worked", async () => {
    mockedSet.mockRejectedValue(
      new ApiError("The last admin cannot be demoted. Promote another admin first.", 409),
    );
    renderPanel();
    await userEvent.selectOptions(
      await screen.findByTestId("users-select-member@example.com"),
      "admin",
    );
    await userEvent.click(screen.getByRole("button", { name: "Change role" }));

    expect(await screen.findByTestId("users-roles-error")).toHaveTextContent("last admin");
    expect(screen.getByTestId("users-role-member@example.com")).toHaveTextContent("member");
  });

  it("tells a member the section needs an admin and loads nothing", () => {
    renderPanel({ ...admin, role: "member" });
    expect(screen.getByTestId("users-roles-forbidden")).toHaveTextContent(
      "This needs the admin role",
    );
    expect(mockedList).not.toHaveBeenCalled();
  });
});
