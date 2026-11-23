import { describe, expect, it } from "vitest";
import { inShort } from "./GoogleAdsSummary";
import type { GoogleAdsRow } from "@/lib/googleAdsApi";

const row = (o: Partial<GoogleAdsRow>): GoogleAdsRow => ({
  campaign_id: "c", name: "x", google_campaign_name: null, clicks: null, spend_source: null,
  chats: 0, calls: 0, hot: 0, paid_orders: 0, ...o,
});

describe("Google Ads, in short", () => {
  it("names the cheapest seller and a campaign with no sale", () => {
    const text = inShort([
      row({ name: "bridal", chats: 22, paid_orders: 3, spent_paise: 210000 }),
      row({ name: "pmax", chats: 5, paid_orders: 0, spent_paise: 70000 }),
    ], true);
    expect(text).toContain('"bridal" brings paying customers at');
    expect(text).toContain('"pmax" had no sale this month');
  });

  it("talks about Hot leads when money is hidden, and says nothing with no chats", () => {
    expect(inShort([row({ name: "a", chats: 4, hot: 2 }), row({ name: "b", chats: 9 })], false)).toBe('"a" brings the most Hot leads (2).');
    expect(inShort([row({ name: "a" })], true)).toBe("");
  });
});
