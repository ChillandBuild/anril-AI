import { describe, expect, it } from "vitest";
import { buildNavAccess } from "@/components/nav/useNavAccess";
import {
  activeSettingsItem,
  claudeSettingsOn,
  getVisibleSettingsItems,
  groupSettingsItems,
  isSettingsPath,
  SETTINGS_GROUP_INFO,
  SETTINGS_GROUP_ORDER,
  SETTINGS_ITEMS,
  settingsItemsFor,
  settingsItemsForMember,
} from "./settingsNavigation";

describe("getVisibleSettingsItems", () => {
  it("fails open for legacy tenants with no subscription item rows", () => {
    const labels = getVisibleSettingsItems([]).map((item) => item.label);

    expect(labels).toContain("Alerts");
  });

  it("hides notification settings without a messaging entitlement", () => {
    const labels = getVisibleSettingsItems(["telecalling_sim"]).map((item) => item.label);

    expect(labels).not.toContain("Alerts");
  });

  it("keeps notification settings for either messaging entitlement", () => {
    const outboundLabels = getVisibleSettingsItems(["outbound_messaging"]).map((item) => item.label);
    const inboundLabels = getVisibleSettingsItems(["inbound_messaging"]).map((item) => item.label);

    expect(outboundLabels).toContain("Alerts");
    expect(inboundLabels).toContain("Alerts");
  });

  it("always exposes Business details regardless of entitlements", () => {
    const noEntitlements = getVisibleSettingsItems([]).map((item) => item.label);
    const simOnly = getVisibleSettingsItems(["telecalling_sim"]).map((item) => item.label);

    expect(noEntitlements).toContain("Business details");
    expect(simOnly).toContain("Business details");
  });
});

describe("Anril AI for Claude", () => {
  it("is hidden unless the caller says it is on", () => {
    expect(getVisibleSettingsItems([]).map((item) => item.label)).not.toContain("Anril AI for Claude");
    expect(getVisibleSettingsItems([], true).map((item) => item.label)).toContain("Anril AI for Claude");
  });

  it("is on only for the owner of a client the operator switched on", () => {
    expect(claudeSettingsOn("owner", ["whatsapp", "claude"])).toBe(true);
    expect(claudeSettingsOn("owner", ["whatsapp"])).toBe(false);
    expect(claudeSettingsOn("caller", ["whatsapp", "claude"])).toBe(false);
    expect(claudeSettingsOn(null, ["claude"])).toBe(false);
  });
});

describe("isSettingsPath", () => {
  it.each([
    "/dashboard/settings/account",
    "/dashboard/settings/connect-channels",
    "/dashboard/settings/telecalling-behavior",
    "/dashboard/settings/notifications",
    "/dashboard/settings/claude",
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

  it.each(["/dashboard/settings", "/dashboard/roles", "/dashboard/roles/x", "/dashboard/subscription"])(
    "%s now counts as a Settings page",
    (path) => {
      expect(isSettingsPath(path)).toBe(true);
    },
  );

  it.each(["/dashboard/subscriptions", "/dashboard/settings-x", "/dashboard/rolesx"])("%s does not", (path) => {
    expect(isSettingsPath(path)).toBe(false);
  });
});

describe("the Settings list", () => {
  it("has the 4 groups in order and one link after them, with the new labels and the same addresses", () => {
    expect(SETTINGS_GROUP_ORDER).toEqual(["My business", "Connections", "Team & roles", "Alerts & automations"]);
    expect(SETTINGS_ITEMS.map((item) => [item.group, item.label, item.href])).toEqual([
      ["My business", "Business details", "/dashboard/settings/account"],
      ["My business", "Anril AI for Claude", "/dashboard/settings/claude"],
      ["My business", "Payments & advance", "/dashboard/settings/payments"],
      ["My business", "Target & profit", "/dashboard/settings/target"],
      ["My business", "Text size", "/dashboard/settings/display"],
      ["Connections", "Channels", "/dashboard/settings/connect-channels"],
      ["Connections", "Calling", "/dashboard/settings/telecalling-behavior"],
      ["Connections", "Calling rules", "/dashboard/settings/calling-rules"],
      ["Connections", "Limits & Meta charges", "/dashboard/settings/meta-charges"],
      ["Team & roles", "Team & roles", "/dashboard/roles"],
      ["Alerts & automations", "Alerts", "/dashboard/settings/alerts"],
      ["Alerts & automations", "Push & lead claims", "/dashboard/settings/notifications"],
      ["Alerts & automations", "Automations", "/dashboard/automations"],
      [null, "Plans & subscription", "/dashboard/subscription"],
    ]);
  });

  it("groups the items for rendering, with Plans & subscription left loose", () => {
    const { groups, loose } = groupSettingsItems(getVisibleSettingsItems([], false));
    expect(groups.map((g) => [g.group, g.items.map((i) => i.label)])).toEqual([
      ["My business", ["Business details", "Payments & advance", "Target & profit", "Text size"]],
      ["Connections", ["Channels", "Calling", "Calling rules", "Limits & Meta charges"]],
      ["Team & roles", ["Team & roles"]],
      ["Alerts & automations", ["Alerts", "Push & lead claims", "Automations"]],
    ]);
    expect(loose.map((i) => i.label)).toEqual(["Plans & subscription"]);
  });

  it("lights the row with the longest matching address", () => {
    expect(activeSettingsItem(SETTINGS_ITEMS, "/dashboard/roles")?.label).toBe("Team & roles");
    expect(activeSettingsItem(SETTINGS_ITEMS, "/dashboard/subscription")?.label).toBe("Plans & subscription");
    expect(activeSettingsItem(SETTINGS_ITEMS, "/dashboard/settings")).toBeNull();
  });
});

describe("per-item gates (desktop)", () => {
  const access = (role: "owner" | "caller", permissions: string[], subStatus = "active") =>
    buildNavAccess({ role, permissions, enabledFeatures: [], subStatus }).access;
  const labels = (a: ReturnType<typeof access>, purchased: string[] = []) =>
    settingsItemsFor(a, purchased, true).map((item) => item.label);

  it("an active owner sees everything (with Claude switched on)", () => {
    expect(labels(access("owner", []))).toEqual([
      "Business details", "Anril AI for Claude", "Payments & advance", "Target & profit", "Text size",
      "Channels", "Calling", "Calling rules", "Limits & Meta charges", "Team & roles", "Alerts", "Push & lead claims", "Automations", "Plans & subscription",
    ]);
  });

  it("an unsubscribed owner sees only Plans & subscription", () => {
    expect(labels(access("owner", [], "none"))).toEqual(["Plans & subscription"]);
    expect(labels(access("owner", [], "pending_approval"))).toEqual(["Plans & subscription"]);
  });

  it("a settings-only member sees the settings pages but not Team & roles or Plans", () => {
    expect(labels(access("caller", ["settings.view"]))).toEqual([
      "Business details", "Anril AI for Claude", "Payments & advance", "Target & profit", "Text size",
      "Channels", "Calling", "Calling rules", "Limits & Meta charges", "Alerts", "Push & lead claims", "Automations",
    ]);
  });

  it("a roles-only subscribed member sees only Team & roles", () => {
    expect(labels(access("caller", ["roles.view"]))).toEqual(["Text size", "Team & roles"]);
    expect(labels(access("caller", ["roles.manage"]))).toEqual(["Text size", "Team & roles"]);
  });

  it("Team & roles needs a subscription even with roles.manage", () => {
    expect(labels(access("caller", ["roles.manage"], "none"))).toEqual([]);
  });

  it("an unsubscribed member with subscription.view still reaches Plans & subscription", () => {
    expect(labels(access("caller", ["subscription.view"], "none"))).toEqual(["Plans & subscription"]);
    expect(labels(access("caller", ["subscription.manage"], "expired"))).toEqual(["Plans & subscription"]);
  });

  it("a telecaller with no settings permissions still sees Text size, and nothing else", () => {
    expect(labels(access("caller", ["leads.view"]))).toEqual(["Text size"]);
    expect(labels(access("caller", []))).toEqual(["Text size"]);
  });

  it("Text size still follows the subscription rule", () => {
    expect(labels(access("caller", ["leads.view"], "none"))).toEqual([]);
    expect(labels(access("caller", ["leads.view"], "expired"))).toEqual([]);
  });

  it("only Text size is open to all; every other row keeps a permission", () => {
    expect(SETTINGS_ITEMS.filter((item) => item.openToAll).map((item) => item.label)).toEqual(["Text size"]);
    expect(SETTINGS_ITEMS.filter((item) => !item.openToAll).every((item) => item.permissionAny.length > 0)).toBe(true);
  });

  it("the My business card describes its new rows", () => {
    expect(SETTINGS_GROUP_INFO["My business"].description).toBe("Business details, payments, your target and text size.");
  });

  it("Alerts still needs the notifications entitlement", () => {
    expect(labels(access("owner", []), ["telecalling_sim"])).not.toContain("Alerts");
    expect(labels(access("owner", []), ["outbound_messaging"])).toContain("Alerts");
  });
});

describe("per-item gates (phone drawer: permissions only, no subscription check, as before)", () => {
  const labels = (role: string | null, permissions: string[]) =>
    settingsItemsForMember(role, permissions, [], false).map((item) => item.label);

  it("owner sees every row", () => {
    expect(labels("owner", [])).toEqual([
      "Business details", "Payments & advance", "Target & profit", "Text size",
      "Channels", "Calling", "Calling rules", "Limits & Meta charges", "Team & roles", "Alerts", "Push & lead claims", "Automations", "Plans & subscription",
    ]);
  });

  it("each row keeps its own permission", () => {
    expect(labels("agent", ["settings.manage"])).toEqual([
      "Business details", "Payments & advance", "Target & profit", "Text size", "Channels", "Calling", "Calling rules", "Limits & Meta charges", "Alerts", "Push & lead claims", "Automations",
    ]);
    expect(labels("agent", ["roles.view"])).toEqual(["Text size", "Team & roles"]);
    expect(labels("agent", ["subscription.manage"])).toEqual(["Text size", "Plans & subscription"]);
    expect(labels("agent", ["leads.view"])).toEqual(["Text size"]);
    expect(labels(null, [])).toEqual(["Text size"]);
  });
});
