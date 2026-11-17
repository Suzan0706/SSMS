// The role picked on a front-page card ("Ingia kama Mkutubi"), kept for this browser tab only. After sign-in the home
// page shows that role's view first, or says plainly when the account does not have that role.
import type { Word } from "./i18n";

const KEY = "ssms.chosenRole";

/** Role codes (as stored on accounts) and their names on the front page. */
export const ROLE_NAMES: Record<string, Word> = {
  school_admin: "wRoleAdmin",
  teacher: "teacher",
  bursar: "wRoleBursar",
  receptionist: "wRoleReception",
  librarian: "wRoleLibrarian",
  student: "wRoleStudent",
  parent: "wRoleParent",
};

export function rememberChosenRole(role: string | null): void {
  try {
    if (role && role in ROLE_NAMES) sessionStorage.setItem(KEY, role);
    else sessionStorage.removeItem(KEY);
  } catch {
    /* storage blocked: the choice is simply not remembered */
  }
}

export function chosenRole(): string | null {
  try {
    const role = sessionStorage.getItem(KEY);
    return role && role in ROLE_NAMES ? role : null;
  } catch {
    return null;
  }
}
