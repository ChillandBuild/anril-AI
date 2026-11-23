// Small pure helpers for sign-in and first setup (v9.2 #27). Everything here is a convenience for
// the owner, not a security wall: Supabase enforces the real sign-in limit, and the server decides
// who may do what.

export const LOGIN_PAUSE_TRIES = 5;
export const LOGIN_PAUSE_MS = 10 * 60 * 1000;
/** Wrong tries older than this no longer count towards the 5. */
export const LOGIN_TRIES_FORGET_MS = 60 * 60 * 1000;
export const LOGIN_TRIES_KEY = "anril_login_tries";

export type LoginTries = { count: number; lastAt: number; pausedUntil: number };

export const NO_TRIES: LoginTries = { count: 0, lastAt: 0, pausedUntil: 0 };

export function parseTries(raw: string | null | undefined): LoginTries {
  try {
    const v = raw ? JSON.parse(raw) : null;
    const num = (x: unknown) => (typeof x === "number" && Number.isFinite(x) && x >= 0 ? x : 0);
    return v && typeof v === "object" ? { count: num(v.count), lastAt: num(v.lastAt), pausedUntil: num(v.pausedUntil) } : NO_TRIES;
  } catch {
    return NO_TRIES;
  }
}

/** One more wrong password. The 5th starts a 10 minute pause. */
export function addWrongTry(tries: LoginTries, now: number): LoginTries {
  const stale = tries.lastAt && now - tries.lastAt > LOGIN_TRIES_FORGET_MS;
  const count = (stale ? 0 : tries.count) + 1;
  if (count >= LOGIN_PAUSE_TRIES) return { count: 0, lastAt: now, pausedUntil: now + LOGIN_PAUSE_MS };
  return { count, lastAt: now, pausedUntil: 0 };
}

export function pauseSecondsLeft(tries: LoginTries, now: number): number {
  return tries.pausedUntil > now ? Math.ceil((tries.pausedUntil - now) / 1000) : 0;
}

/** 600 -> "10:00" */
export function formatCountdown(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** Only a wrong email/password counts; a network failure or a busy server does not. */
export function isWrongPasswordError(err: { code?: string; message?: string } | null | undefined): boolean {
  if (!err) return false;
  return err.code === "invalid_credentials" || /invalid login credentials/i.test(err.message ?? "");
}

export function readTries(): LoginTries {
  try {
    return parseTries(window.localStorage.getItem(LOGIN_TRIES_KEY));
  } catch {
    return NO_TRIES;
  }
}

export function writeTries(tries: LoginTries): void {
  try {
    if (tries.count === 0 && tries.pausedUntil === 0) window.localStorage.removeItem(LOGIN_TRIES_KEY);
    else window.localStorage.setItem(LOGIN_TRIES_KEY, JSON.stringify(tries));
  } catch {
    // Private window or blocked storage: no pause, Supabase's own limit still applies.
  }
}

/** The Anril team makes the login with a temporary password; the owner changes it on first sign-in. */
export function mustChangePassword(user: { user_metadata?: Record<string, unknown> | null } | null | undefined): boolean {
  return user?.user_metadata?.must_change_password === true;
}

export const MIN_PASSWORD_LENGTH = 8;

/** The words shown under the change-password form, or null when it is fine to save. */
export function checkNewPassword(input: { current: string; next: string; again: string }): string | null {
  if (!input.current) return "Type the password you were given";
  if (input.next.length < MIN_PASSWORD_LENGTH) return `The new password needs at least ${MIN_PASSWORD_LENGTH} characters`;
  if (input.next === input.current) return "The new password must be different from the old one";
  if (input.next !== input.again) return "The two new passwords don't match";
  return null;
}

/** Next.js gives an error a short digest. Show it as a code the owner can read out to the Anril team. */
export function errorCode(digest: string | null | undefined): string | null {
  const d = (digest ?? "").replace(/[^A-Za-z0-9]/g, "").slice(0, 10);
  return d || null;
}

/** 15 characters: 2 digits (state), 5 letters, 4 digits, a letter, then 1, Z and a check character. */
export const GSTIN_PATTERN = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;
