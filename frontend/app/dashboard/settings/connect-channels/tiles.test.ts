import { describe, expect, test } from "vitest";
import { assetFor, channelStatus, connectionNote, marketplaceStatus } from "./tiles";
import type { Setting, WebhookHealth } from "./channels";

function setting(key: string, display_value: string, is_set = true): Setting {
  return { key, display_value, is_secret: false, is_set, updated_at: "2026-08-11T00:00:00Z" };
}

const facebookConfigured = [setting("facebook_page_id", "123"), setting("facebook_access_token", "••••", true)];

describe("channelStatus", () => {
  test("not configured is off", () => {
    expect(channelStatus("facebook", [], null).state).toBe("off");
  });
  test("a token alert beats every other state", () => {
    const health: WebhookHealth = { health: {}, token_alerts: [{ channel: "facebook", error: "x", created_at: "" }] };
    expect(channelStatus("facebook", facebookConfigured, health).label).toBe("Needs attention");
  });
  test("configured with no event is quiet, with an event is receiving", () => {
    expect(channelStatus("facebook", facebookConfigured, null).state).toBe("waiting");
    const health: WebhookHealth = { health: { facebook: { last_event: new Date().toISOString() } }, token_alerts: [] };
    expect(channelStatus("facebook", facebookConfigured, health).state).toBe("receiving");
  });
});

describe("marketplaceStatus", () => {
  test("off, quiet and receiving", () => {
    expect(marketplaceStatus(null).state).toBe("off");
    expect(marketplaceStatus({ connected: true, last_lead_at: null, leads_this_month: 0 }).state).toBe("waiting");
    expect(marketplaceStatus({ connected: true, last_lead_at: new Date().toISOString(), leads_this_month: 3 }).state).toBe("receiving");
  });
});

describe("assetFor", () => {
  test("is empty when nothing is stored", () => {
    expect(assetFor("meta_ads", [])).toEqual({ id: null, label: null });
    expect(assetFor("indiamart", [])).toEqual({ id: null, label: null });
  });
  test("pairs the WhatsApp number with the verified name", () => {
    const s = [setting("meta_phone_display", "+91 95009 98088"), setting("meta_verified_name", "Kelir")];
    expect(assetFor("whatsapp", s)).toEqual({ id: "+91 95009 98088", label: "Kelir" });
  });
  test("shows the Instagram handle via the linked Page", () => {
    expect(assetFor("instagram", [setting("instagram_username", "astro")])).toEqual({ id: "@astro", label: "via linked Page" });
  });
});

describe("connectionNote", () => {
  const manual = [...facebookConfigured, setting("facebook_connection_source", "manual")];
  test("names own API keys for a Meta channel connected by hand", () => {
    expect(connectionNote("facebook", "waiting", manual)).toBe(" · via your own API keys");
  });
  test("says nothing when connected through Meta Business or not connected", () => {
    const embedded = [...facebookConfigured, setting("facebook_connection_source", "embedded")];
    expect(connectionNote("facebook", "waiting", embedded)).toBe("");
    expect(connectionNote("facebook", "off", manual)).toBe("");
    expect(connectionNote("telegram", "waiting", [])).toBe("");
  });
});
