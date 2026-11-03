import { describe, expect, it } from "vitest";
import { getHomeHref, isActive, isSmsOnly } from "./utils";

describe("isActive", () => {
  it("returns true for an exact path match", () => {
    expect(isActive("/dashboard/telecalling", "/dashboard/telecalling")).toBe(true);
  });

  it("returns true for a nested path under href", () => {
    expect(isActive("/dashboard/telecalling/scheduled", "/dashboard/telecalling")).toBe(true);
  });

  it("returns false for an unrelated path", () => {
    expect(isActive("/dashboard/conversations", "/dashboard/telecalling")).toBe(false);
  });

  it("returns false for a path that merely starts with the same characters", () => {
    expect(isActive("/dashboard/telecallingX", "/dashboard/telecalling")).toBe(false);
  });
});

describe("getHomeHref", () => {
  it("returns /dashboard/profile for callers", () => {
    expect(getHomeHref("caller")).toBe("/dashboard/profile");
  });

  it("returns /dashboard for owners", () => {
    expect(getHomeHref("owner")).toBe("/dashboard");
  });

  it("returns /dashboard while role is still loading (null)", () => {
    expect(getHomeHref(null)).toBe("/dashboard");
  });
});

describe("isSmsOnly", () => {
  it("is true when SMS is the only product switched on", () => {
    expect(isSmsOnly(["sms"])).toBe(true);
    expect(isSmsOnly(["sms", "sms.extra"])).toBe(true);
  });

  it("is false when any other product is on, or SMS is off", () => {
    for (const other of ["whatsapp", "outbound_messaging", "inbound_messaging", "telecalling_sim", "telecalling_telecmi", "telecalling.dialer"]) {
      expect(isSmsOnly(["sms", other]), other).toBe(false);
    }
    expect(isSmsOnly([])).toBe(false);
    expect(isSmsOnly(["whatsapp"])).toBe(false);
  });
});
