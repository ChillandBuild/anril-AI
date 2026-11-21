import { describe, expect, it } from "vitest";
import { chipRowFor } from "./chipRow";
import { buildNavAccess } from "./useNavAccess";

const owner = buildNavAccess({
  role: "owner",
  permissions: [],
  enabledFeatures: ["outbound_messaging", "inbound_messaging", "sms", "whatsapp"],
  subStatus: "active",
}).access;

const labels = (pathname: string, access = owner, tab = "") => chipRowFor(pathname, access, tab)?.chips.map((c) => c.label);
const active = (pathname: string, access = owner, tab = "") => chipRowFor(pathname, access, tab)?.activeHref;

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

describe("chipRowFor: Calling and Leads to call (query-aware)", () => {
  const telecalling = buildNavAccess({
    role: "owner",
    permissions: [],
    enabledFeatures: ["telecalling_sim", "telecalling.upload", "telecalling.dialer", "telecalling.scheduled", "telecalling.notes"],
    subStatus: "active",
  }).access;
  const CALLING = ["Call from the queue", "Dial a number", "Scripts"];
  const LEADS = ["Call lists", "Scheduled calls", "Uploads", "Who got which lead"];

  it.each([
    ["/dashboard/telecalling", "", CALLING, "/dashboard/telecalling"],
    ["/dashboard/telecalling/dial", "", CALLING, "/dashboard/telecalling/dial"],
    ["/dashboard/telecalling/upload", "scripts", CALLING, "/dashboard/telecalling/upload?tab=scripts"],
    ["/dashboard/telecalling/upload", "", LEADS, "/dashboard/telecalling/upload"],
    ["/dashboard/telecalling/upload", "upload", LEADS, "/dashboard/telecalling/upload"],
    ["/dashboard/telecalling/upload", "history", LEADS, "/dashboard/telecalling/upload?tab=history"],
    ["/dashboard/telecalling/scheduled", "", LEADS, "/dashboard/telecalling/scheduled"],
    ["/dashboard/team", "log", LEADS, "/dashboard/team?tab=log"],
  ])("%s ?tab=%s shows its set in order with the right chip active", (path, tab, expected, activeHref) => {
    expect(labels(path, telecalling, tab)).toEqual(expected);
    expect(active(path, telecalling, tab)).toBe(activeHref);
  });

  it("Team (performance) and Call reviews have no chips", () => {
    expect(chipRowFor("/dashboard/team", telecalling, "")).toBeNull();
    expect(chipRowFor("/dashboard/notes", telecalling, "")).toBeNull();
  });

  it("a telecaller with only the dialer gets the queue and dial chips, with no Scripts chip", () => {
    const dialer = buildNavAccess({
      role: "caller", permissions: ["telecalling.dialer"], enabledFeatures: ["telecalling_sim", "telecalling.dialer"], subStatus: "active",
    }).access;
    expect(labels("/dashboard/telecalling", dialer)).toEqual(["Call from the queue", "Dial a number"]);
  });

  it("a user with only the Upload gate has no Calling row (one chip), but Call lists and Uploads show", () => {
    const upload = buildNavAccess({
      role: "caller", permissions: ["telecalling.upload"], enabledFeatures: ["telecalling_sim", "telecalling.upload"], subStatus: "active",
    }).access;
    expect(chipRowFor("/dashboard/telecalling/upload", upload, "scripts")).toBeNull();
    expect(labels("/dashboard/telecalling/upload", upload, "history")).toEqual(["Call lists", "Uploads"]);
  });

  it("a user with only team.view gets no chip row on the log (one chip)", () => {
    const team = buildNavAccess({ role: "caller", permissions: ["team.view"], enabledFeatures: [], subStatus: "active" }).access;
    expect(chipRowFor("/dashboard/team", team, "log")).toBeNull();
  });
});
