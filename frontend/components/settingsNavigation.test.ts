import { describe, expect, it } from "vitest";
import { getVisibleSettingsItems, isSettingsPath, SETTINGS_GROUP_ORDER, SETTINGS_ITEMS } from "./settingsNavigation";

describe("getVisibleSettingsItems", () => {
  it("fails open for legacy tenants with no subscription item rows", () => {
    const labels = getVisibleSettingsItems([]).map((item) => item.label);

    expect(labels).toContain("Notifications");
  });

  it("hides notification settings without a messaging entitlement", () => {
    const labels = getVisibleSettingsItems(["telecalling_sim"]).map((item) => item.label);

    expect(labels).not.toContain("Notifications");
  });

  it("keeps notification settings for either messaging entitlement", () => {
    const outboundLabels = getVisibleSettingsItems(["outbound_messaging"]).map((item) => item.label);
    const inboundLabels = getVisibleSettingsItems(["inbound_messaging"]).map((item) => item.label);

    expect(outboundLabels).toContain("Notifications");
    expect(inboundLabels).toContain("Notifications");
  });

  it("always exposes Profile & Business regardless of entitlements", () => {
    const noEntitlements = getVisibleSettingsItems([]).map((item) => item.label);
    const simOnly = getVisibleSettingsItems(["telecalling_sim"]).map((item) => item.label);

    expect(noEntitlements).toContain("Profile & Business");
    expect(simOnly).toContain("Profile & Business");
  });
});

describe("isSettingsPath", () => {
  it.each([
    "/dashboard/settings/account",
    "/dashboard/settings/connect-channels",
    "/dashboard/settings/telecalling-behavior",
    "/dashboard/settings/notifications",
  ])("%s is a Settings page", (path) => {
    expect(isSettingsPath(path)).toBe(true);
  });

  it.each([
    "/dashboard/settings/auto-reply",
    "/dashboard/settings/follow-ups",
    "/dashboard/settings/inbox",
    "/dashboard/otp/settings",
    "/dashboard",
  ])("%s no longer puts the sidebar in Settings mode", (path) => {
    expect(isSettingsPath(path)).toBe(false);
  });

  it("the Anril settings group is gone from the list and the group order", () => {
    expect(SETTINGS_ITEMS.map((item) => item.label)).toEqual([
      "Profile & Business", "Connect Channels", "Telecalling Behavior", "Notifications",
    ]);
    expect(SETTINGS_GROUP_ORDER).not.toContain("Anril");
  });
});
