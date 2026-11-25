import { describe, expect, it } from "vitest";
import { pickActiveTab } from "./mobileNavActive";

const MORE = "/dashboard/more";
const TABS = ["/dashboard", "/dashboard/conversations", "/dashboard/telecalling", "/dashboard/leads", MORE];

describe("pickActiveTab", () => {
  it("lights More for pages opened from More", () => {
    expect(pickActiveTab(TABS, "/dashboard/templates", MORE)).toBe(MORE);
    expect(pickActiveTab(TABS, "/dashboard/settings/account", MORE)).toBe(MORE);
  });

  it("lights a tab for its own pages", () => {
    expect(pickActiveTab(TABS, "/dashboard/leads/abc", MORE)).toBe("/dashboard/leads");
    expect(pickActiveTab(TABS, "/dashboard/conversations", MORE)).toBe("/dashboard/conversations");
    expect(pickActiveTab(TABS, MORE, MORE)).toBe(MORE);
  });

  it("lights Home only on Home itself", () => {
    expect(pickActiveTab(TABS, "/dashboard", MORE)).toBe("/dashboard");
  });

  it("lights nothing when the bar has no More tab", () => {
    expect(pickActiveTab(["/dashboard", "/dashboard/subscription"], "/dashboard/templates", MORE)).toBeUndefined();
  });

  it("lights nothing outside the dashboard", () => {
    expect(pickActiveTab(TABS, "/login", MORE)).toBeUndefined();
  });
});
