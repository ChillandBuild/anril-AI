import { describe, expect, test } from "vitest";
import { accountLine, channelStatus, countStates, marketplaceStatus, summarySentence } from "./tiles";
import type { Setting, WebhookHealth } from "./channels";

function setting(key: string, display_value: string, is_set = true): Setting {
  return { key, display_value, is_secret: false, is_set, updated_at: "2026-08-11T00:00:00Z" };
}

const facebookConfigured = [setting("facebook_page_id", "123"), setting("facebook_access_token", "••••", true)];

describe("countStates", () => {
  test("splits connected states into receiving, quiet, attention and off", () => {
    const c = countStates(["receiving", "synced", "waiting", "attention", "off", "off"]);
    expect(c).toEqual({ connected: 4, total: 6, receiving: 2, quiet: 1, attention: 1, off: 2 });
  });
});

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

describe("accountLine", () => {
  test("shows an em dash when nothing is stored", () => {
    expect(accountLine("meta_ads", [])).toBe("—");
    expect(accountLine("indiamart", [])).toBe("—");
  });
  test("builds the Instagram handle line", () => {
    expect(accountLine("instagram", [setting("instagram_username", "astro")])).toBe("@astro · via linked Page");
  });
});

describe("summarySentence", () => {
  test("names connected chat channels and the missing lead sources", () => {
    const s = summarySentence({ whatsapp: "receiving", instagram: "receiving", facebook: "waiting", indiamart: "off", justdial: "off" });
    expect(s).toBe("Customers can reach you on WhatsApp, Instagram and Messenger. Connect IndiaMART or JustDial to bring their enquiries in too.");
  });
  test("asks for a first channel when none is connected", () => {
    expect(summarySentence({ whatsapp: "off" })).toContain("Connect WhatsApp, Instagram or Messenger");
  });
});
