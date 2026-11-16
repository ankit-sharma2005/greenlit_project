import { describe, expect, it } from "vitest";

import { isRoleRefusal, ROLE_HINT } from "./roleHint";

describe("roleHint", () => {
  it("names the role the action needs and who can grant it", () => {
    expect(ROLE_HINT).toBe(
      "This needs the reviewer or admin role. Ask an admin to change your role.",
    );
  });

  it("recognises the server's role refusal, and nothing else", () => {
    expect(isRoleRefusal("Your role does not allow this action.")).toBe(true);
    expect(isRoleRefusal("  Your role does not allow this action. ")).toBe(true);
    expect(isRoleRefusal("The last admin cannot be demoted.")).toBe(false);
    expect(isRoleRefusal(null)).toBe(false);
    expect(isRoleRefusal(undefined)).toBe(false);
  });
});
