import { describe, expect, it } from "vitest";
import { chipRowFor } from "./chipRow";
import { buildNavAccess } from "./useNavAccess";

const owner = buildNavAccess({
  role: "owner",
  permissions: [],
  enabledFeatures: ["outbound_messaging", "inbound_messaging", "sms", "whatsapp"],
  subStatus: "active",
}).access;

const labels = (pathname: string, access = owner) => chipRowFor(pathname, access)?.chips.map((c) => c.label);
const active = (pathname: string, access = owner) => chipRowFor(pathname, access)?.activeHref;

const AUTO = ["When something happens", "Follow-ups", "One-time sends"];
const REPLIES = ["Auto-reply", "Handover"];
const OTP = ["Rules", "Connect your website"];

describe("chipRowFor: the 7 chip pages", () => {
  it.each([
    ["/dashboard/auto-messages", AUTO, "/dashboard/auto-messages"],
    ["/dashboard/settings/follow-ups", AUTO, "/dashboard/settings/follow-ups"],
    ["/dashboard/scheduled-templates", AUTO, "/dashboard/scheduled-templates"],
    ["/dashboard/settings/auto-reply", REPLIES, "/dashboard/settings/auto-reply"],
    ["/dashboard/settings/inbox", REPLIES, "/dashboard/settings/inbox"],
    ["/dashboard/otp/settings", OTP, "/dashboard/otp/settings"],
    ["/dashboard/otp/api", OTP, "/dashboard/otp/api"],
  ])("%s shows its set in order with itself active", (path, expected, activeHref) => {
    expect(labels(path)).toEqual(expected);
    expect(active(path)).toBe(activeHref);
  });

  it("exactly one chip is active", () => {
    for (const path of ["/dashboard/auto-messages", "/dashboard/settings/inbox", "/dashboard/otp/api"]) {
      const row = chipRowFor(path, owner)!;
      expect(row.chips.filter((c) => c.href === row.activeHref)).toHaveLength(1);
    }
  });

  it("a sub-path keeps its chip active", () => {
    expect(active("/dashboard/scheduled-templates/123")).toBe("/dashboard/scheduled-templates");
  });
});

describe("chipRowFor: no row", () => {
  it.each(["/dashboard", "/dashboard/otp", "/dashboard/otp/history", "/dashboard/settings/general", "/dashboard/meta-ads"])(
    "%s has no chips",
    (path) => expect(chipRowFor(path, owner)).toBeNull(),
  );
});

describe("chipRowFor: hides chips the user cannot open", () => {
  it("drops a hidden chip and keeps order", () => {
    // Settings holders without messaging features: Follow-ups stays, the other two go, so one chip is left -> no row.
    const settingsOnly = buildNavAccess({ role: "caller", permissions: ["settings.view"], enabledFeatures: [], subStatus: "active" }).access;
    expect(chipRowFor("/dashboard/settings/follow-ups", settingsOnly)).toBeNull();

    const twoOfThree = buildNavAccess({
      role: "caller",
      permissions: ["settings.view", "auto_messages.view"],
      enabledFeatures: ["outbound_messaging"],
      subStatus: "active",
    }).access;
    expect(labels("/dashboard/auto-messages", twoOfThree)).toEqual(["When something happens", "Follow-ups"]);
  });

  it("no row when fewer than 2 chips are visible", () => {
    const callerNone = buildNavAccess({ role: "caller", permissions: [], enabledFeatures: [], subStatus: "active" }).access;
    expect(chipRowFor("/dashboard/settings/auto-reply", callerNone)).toBeNull();
    expect(chipRowFor("/dashboard/otp/settings", callerNone)).toBeNull();
  });

  it("an expired subscription hides every chip", () => {
    const expired = buildNavAccess({ role: "owner", permissions: [], enabledFeatures: ["outbound_messaging"], subStatus: "expired" }).access;
    expect(chipRowFor("/dashboard/settings/inbox", expired)).toBeNull();
  });
});
