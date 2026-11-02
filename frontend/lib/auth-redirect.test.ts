import { describe, expect, it } from "vitest";
import { safeNext } from "./auth-redirect";

describe("safeNext", () => {
  it("allows the two in-app destinations", () => {
    expect(safeNext("/dashboard")).toBe("/dashboard");
    expect(safeNext("/reset-password")).toBe("/reset-password");
  });

  it("falls back to /dashboard when missing", () => {
    expect(safeNext(null)).toBe("/dashboard");
    expect(safeNext(undefined)).toBe("/dashboard");
    expect(safeNext("")).toBe("/dashboard");
  });

  it.each([
    "//evil.com",
    "https://evil.com",
    "/\\evil.com",
    "/dashboard/../../evil",
    "/reset-password?x=1",
    "/settings",
    "javascript:alert(1)",
  ])("rejects %s", (value) => {
    expect(safeNext(value)).toBe("/dashboard");
  });
});
