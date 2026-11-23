import { describe, expect, it } from "vitest";
import { OPERATOR_AUTH_COOKIE, isDashboardAuthCookie, isOperatorPath } from "./operator";

describe("operator login is separate from the dashboard login", () => {
  it("treats only /operator pages as operator pages", () => {
    expect(isOperatorPath("/operator")).toBe(true);
    expect(isOperatorPath("/operator/login")).toBe(true);
    expect(isOperatorPath("/operator/oauth/consent")).toBe(true);
    expect(isOperatorPath("/operator-notes")).toBe(false);
    expect(isOperatorPath("/dashboard/leads")).toBe(false);
    expect(isOperatorPath("/login")).toBe(false);
    expect(isOperatorPath(null)).toBe(false);
  });

  it("uses a cookie name that is not the dashboard's", () => {
    expect(isDashboardAuthCookie("sb-abcdefgh-auth-token")).toBe(true);
    expect(isDashboardAuthCookie("sb-abcdefgh-auth-token.0")).toBe(true);
    expect(isDashboardAuthCookie(OPERATOR_AUTH_COOKIE)).toBe(false);
    expect(isDashboardAuthCookie(`${OPERATOR_AUTH_COOKIE}.1`)).toBe(false);
    expect(isDashboardAuthCookie("theme")).toBe(false);
  });
});
