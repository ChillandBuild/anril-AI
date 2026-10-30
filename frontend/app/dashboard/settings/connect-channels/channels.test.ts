import { describe, expect, test } from "vitest";
import { CHANNELS, META_CHANNELS, STANDALONE_CHANNELS, buildSettingsUpdates, hasUnsavedChanges, isChannelConfigured, razorpayOAuthAccount, resolveConnectionSource } from "./channels";
import type { FieldDef, Setting } from "./channels";

function setting(key: string, display_value: string, is_set = true): Setting {
  return { key, display_value, is_secret: false, is_set, updated_at: "2026-08-11T00:00:00Z" };
}

describe("resolveConnectionSource", () => {
  test("returns embedded when the channel is explicitly marked embedded", () => {
    const settings = [setting("instagram_connection_source", "embedded")];
    expect(resolveConnectionSource("instagram", settings)).toBe("embedded");
  });

  test("explicit manual wins over the embedded fallback signal", () => {
    const settings = [
      setting("instagram_connection_source", "manual"),
      { ...setting("meta_business_access_token", "EAAG••••1234"), is_secret: true },
    ];
    expect(resolveConnectionSource("instagram", settings)).toBe("manual");
  });

  test("falls back to embedded for legacy tenants that have a Meta business token", () => {
    const settings = [{ ...setting("meta_business_access_token", "EAAG••••1234"), is_secret: true }];
    expect(resolveConnectionSource("whatsapp", settings)).toBe("embedded");
  });

  test("falls back to manual when no marker and no Meta business token exist", () => {
    expect(resolveConnectionSource("whatsapp", [setting("meta_waba_id", "123")])).toBe("manual");
  });

  test("non-Meta channels are always manual", () => {
    const settings = [{ ...setting("meta_business_access_token", "EAAG••••1234"), is_secret: true }];
    expect(resolveConnectionSource("telegram", settings)).toBe("manual");
    expect(resolveConnectionSource("razorpay", settings)).toBe("manual");
  });
});

describe("channel grouping", () => {
  test("splits the four Meta channels from the standalone ones", () => {
    expect(META_CHANNELS.map(c => c.id)).toEqual(["whatsapp", "instagram", "facebook", "meta_ads"]);
    // astro_bridge is ops-entered in the operator console, not a tenant self-service
    // channel, so it is not in CHANNELS. See operator/client/[id]/views/config.tsx.
    expect(STANDALONE_CHANNELS.map(c => c.id)).toEqual(["telegram", "razorpay"]);
  });
});

describe("buildSettingsUpdates", () => {
  const razorpayFields: FieldDef[] = [
    { key: "razorpay_key_id", label: "Key ID", secret: false },
    { key: "razorpay_key_secret", label: "Key Secret", secret: true },
    { key: "razorpay_webhook_secret", label: "Webhook Secret", secret: true },
  ];
  const secretSetting = (key: string, is_set: boolean): Setting => ({
    ...setting(key, is_set ? "••••1234" : "Not set", is_set),
    is_secret: true,
  });
  const stored = [
    setting("razorpay_key_id", "rzp_live_OLD"),
    secretSetting("razorpay_key_secret", true),
    secretSetting("razorpay_webhook_secret", true),
  ];

  test("a blank stored secret is left alone, never sent as a delete", () => {
    const drafts = { razorpay_key_id: "rzp_live_NEW", razorpay_key_secret: "typed", razorpay_webhook_secret: "" };
    expect(buildSettingsUpdates(razorpayFields, drafts, stored)).toEqual({
      razorpay_key_id: "rzp_live_NEW",
      razorpay_key_secret: "typed",
    });
  });

  test("only the webhook secret typed: the key secret is not wiped", () => {
    const drafts = { razorpay_key_id: "rzp_live_OLD", razorpay_key_secret: "", razorpay_webhook_secret: "hook" };
    expect(buildSettingsUpdates(razorpayFields, drafts, stored)).toEqual({ razorpay_webhook_secret: "hook" });
  });

  test("a first-time secret with no stored row is sent", () => {
    const settings = [setting("razorpay_key_id", "rzp_live_OLD"), secretSetting("razorpay_key_secret", false)];
    const drafts = { razorpay_key_secret: "fresh" };
    expect(buildSettingsUpdates(razorpayFields, drafts, settings)).toEqual({ razorpay_key_secret: "fresh" });
  });

  test("a plain field the user emptied is still sent so it can be cleared", () => {
    const drafts = { razorpay_key_id: "" };
    expect(buildSettingsUpdates(razorpayFields, drafts, stored)).toEqual({ razorpay_key_id: "" });
  });

  test("an untouched form sends nothing", () => {
    const drafts = { razorpay_key_id: "rzp_live_OLD", razorpay_key_secret: "", razorpay_webhook_secret: "" };
    expect(buildSettingsUpdates(razorpayFields, drafts, stored)).toEqual({});
  });
});

describe("hasUnsavedChanges", () => {
  const fields: FieldDef[] = [
    { key: "razorpay_key_id", label: "Key ID", secret: false },
    { key: "razorpay_key_secret", label: "Key Secret", secret: true },
  ];
  const stored = [
    setting("razorpay_key_id", "rzp_live_OLD"),
    { ...setting("razorpay_key_secret", "••••1234"), is_secret: true },
  ];

  test("a stored secret alone does not make the form dirty", () => {
    expect(hasUnsavedChanges(fields, { razorpay_key_id: "rzp_live_OLD", razorpay_key_secret: "" }, stored)).toBe(false);
  });

  test("typing a secret makes it dirty", () => {
    expect(hasUnsavedChanges(fields, { razorpay_key_secret: "x" }, stored)).toBe(true);
  });

  test("editing a plain field makes it dirty", () => {
    expect(hasUnsavedChanges(fields, { razorpay_key_id: "rzp_live_NEW" }, stored)).toBe(true);
  });
});

describe("Razorpay connected through OAuth", () => {
  const razorpay = CHANNELS.find(c => c.id === "razorpay")!;

  test("the OAuth account stands in for the pasted keys", () => {
    const settings = [setting("razorpay_oauth_account_id", "acc_Dhk2qDbmu6FwZH")];
    expect(razorpayOAuthAccount(settings)).toBe("acc_Dhk2qDbmu6FwZH");
    expect(isChannelConfigured(razorpay, settings)).toBe(true);
  });

  test("without OAuth, all required keys are still needed", () => {
    const settings = [setting("razorpay_key_id", "rzp_live_x")];
    expect(razorpayOAuthAccount(settings)).toBeNull();
    expect(isChannelConfigured(razorpay, settings)).toBe(false);
  });

  test("an OAuth account never configures another channel", () => {
    const telegram = CHANNELS.find(c => c.id === "telegram")!;
    expect(isChannelConfigured(telegram, [setting("razorpay_oauth_account_id", "acc_x")])).toBe(false);
  });
});
