/**
 * The Operator Console keeps its own Supabase login, separate from the client dashboard.
 *
 * Both live on one website, and a browser keeps ONE auth cookie per site, so a shared login meant
 * signing in to one signed you out of the other (you had to close a tab to open the other side).
 * Giving the console its own cookie name lets an operator and a client be signed in side by side.
 */
export const OPERATOR_AUTH_COOKIE = "sb-operator-auth-token";

/** Every page under /operator (console, login, Claude consent screen) uses the operator login. */
export function isOperatorPath(pathname: string | null | undefined): boolean {
  return pathname === "/operator" || (pathname ?? "").startsWith("/operator/");
}

/** The dashboard's own auth cookie: any Supabase auth cookie that is not the operator's. */
export function isDashboardAuthCookie(name: string): boolean {
  return name.startsWith("sb-") && name.includes("-auth-token") && !name.startsWith(OPERATOR_AUTH_COOKIE);
}
