// Where /auth/callback may send someone after it exchanges a code. Exact matches
// only: anything else (another site, "//host", a path we don't expect) would turn
// the callback into an open redirect, so it falls back to the dashboard.
const ALLOWED_NEXT = new Set(["/dashboard", "/reset-password"]);

export function safeNext(next: string | null | undefined): string {
  return next && ALLOWED_NEXT.has(next) ? next : "/dashboard";
}

// Set by /auth/callback after a password-recovery link is exchanged. The
// /reset-password page only shows its form when this short-lived cookie is
// present, so an ordinary signed-in session can't change the password there
// without the current one.
export const RESET_COOKIE = "anril_pw_recovery";
export const RESET_COOKIE_MAX_AGE = 15 * 60;
