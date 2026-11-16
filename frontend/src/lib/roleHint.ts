/** A second line shown next to a role refusal: what the action needs, and who can grant it. */

const GENERIC_REFUSAL = "Your role does not allow this action.";

export const ROLE_HINT =
  "This needs the reviewer or admin role. Ask an admin to change your role.";

/** True when the message is the server's role refusal (the exact text the guards send). */
export function isRoleRefusal(message: string | null | undefined): boolean {
  return typeof message === "string" && message.trim() === GENERIC_REFUSAL;
}
