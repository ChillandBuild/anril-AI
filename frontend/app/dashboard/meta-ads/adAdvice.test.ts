import { describe, expect, it } from "vitest";
import { adviceFor } from "./adAdvice";

const TODAY = "2026-11-19";

const ad = (id: string, values: Partial<Parameters<typeof adviceFor>[0][number]> = {}) => ({
  ad_creative_id: id,
  delivery_status: "ACTIVE",
  spend: 2000,
  messages: 40,
  hot: 8,
  booked: 3,
  paid: 1,
  schedule_end: null,
  ...values,
});

function keys(rows: ReturnType<typeof ad>[]) {
  const advice = adviceFor(rows, TODAY);
  return Object.fromEntries(rows.map((row) => [row.ad_creative_id, advice.get(row.ad_creative_id)?.key]));
}

describe("adviceFor", () => {
  it("calls an ad too early under ₹500 or under 10 chats, before anything else", () => {
    expect(keys([ad("a", { spend: 320 }), ad("b", { messages: 6 }), ad("c")])).toMatchObject({ a: "too_early", b: "too_early" });
    expect(adviceFor([ad("a", { spend: 320 })], TODAY).get("a")?.reason).toContain("₹320");
  });

  it("gives Best to the one running, paying ad with the cheapest hot leads", () => {
    const rows = [
      ad("cheap", { spend: 1000, hot: 10 }),            // ₹100 per hot lead
      ad("dear", { spend: 3000, hot: 10 }),             // ₹300
      ad("cheaper-but-off", { spend: 500, hot: 10, delivery_status: "PAUSED" }),
      ad("cheapest-no-pay", { spend: 600, hot: 12, paid: 0 }),
    ];
    const result = keys(rows);
    expect(result.cheap).toBe("best");
    expect(Object.values(result).filter((k) => k === "best")).toHaveLength(1);
    expect(adviceFor(rows, TODAY).get("cheap")?.reason).toBe("Your cheapest hot leads (₹100 each) and 1 paid.");
  });

  it("flags 20+ chats with no bookings", () => {
    expect(keys([ad("a", { messages: 130, booked: 0, paid: 0 })]).a).toBe("no_customers");
    expect(keys([ad("a", { messages: 19, booked: 0, paid: 0 }), ad("b")]).a).not.toBe("no_customers");
  });

  it("calls an ad costly over twice the average, by whether it still runs", () => {
    const rows = [
      ad("base1", { spend: 1000, hot: 10, paid: 0 }),
      ad("base2", { spend: 1000, hot: 10, paid: 0 }),
      ad("base3", { spend: 1000, hot: 10, paid: 0 }),
      ad("dear-on", { spend: 5000, hot: 5, paid: 0 }),        // ₹1,000 vs ₹229 average
      ad("dear-off", { spend: 5000, hot: 5, paid: 0, delivery_status: "PAUSED" }),
      ad("no-hot", { spend: 900, hot: 0, paid: 0 }),
    ];
    const result = keys(rows);
    expect(result["dear-on"]).toBe("costly_running");
    expect(result["dear-off"]).toBe("costly_stopped");
    expect(result["no-hot"]).toBe("costly_running");
    expect(result.base1).toBe("ok");
  });

  it("says Ended on schedule for a stopped ad past its end date, else Doing okay", () => {
    const rows = [
      ad("ended", { delivery_status: "PAUSED", paid: 0, schedule_end: "2026-11-12T00:00:00+0530" }),
      ad("future-end", { delivery_status: "PAUSED", paid: 0, schedule_end: "2026-12-01T00:00:00+0530" }),
    ];
    expect(keys(rows)).toEqual({ ended: "ended", "future-end": "ok" });
  });

  it("has no costly or average tips when no ad has a hot lead", () => {
    const result = adviceFor([ad("a", { hot: 0, paid: 0 })], TODAY).get("a");
    expect(result).toEqual({ key: "ok", label: "Doing okay", reason: "Nothing stands out yet." });
  });
});
