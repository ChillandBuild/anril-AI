import { describe, expect, it } from "vitest";

import { orderOverviewCards, overviewKind } from "./overviewCardOrder";

const keys = (cards: { key: string }[]) => cards.map((c) => c.key);
// The order the backend sends for a business that uses orders, calls, ads and bookings.
const SENT = ["sales_paise", "paid", "first_chats", "hot", "calls", "bookings"].map((key) => ({ key }));

describe("overviewKind", () => {
  it("reads the free-text business type", () => {
    expect(overviewKind("Healthcare")).toBe("service");
    expect(overviewKind("Salon & spa")).toBe("service");
    expect(overviewKind("Real Estate")).toBe("leads");
    expect(overviewKind("Coaching")).toBe("leads");
    expect(overviewKind("E-commerce")).toBe("shop");
    expect(overviewKind("Retail & grocery")).toBe("shop");
  });

  it("returns null for Other, empty or unknown", () => {
    expect(overviewKind("Other")).toBeNull();
    expect(overviewKind("Agency")).toBeNull();
    expect(overviewKind("")).toBeNull();
    expect(overviewKind(null)).toBeNull();
    expect(overviewKind(undefined)).toBeNull();
  });
});

describe("orderOverviewCards", () => {
  it("puts Bookings first for a clinic", () => {
    expect(keys(orderOverviewCards(SENT, "Healthcare"))).toEqual(["bookings", "first_chats", "paid", "sales_paise", "hot", "calls"]);
  });

  it("puts Sales and Paid first for a shop", () => {
    expect(keys(orderOverviewCards(SENT, "Retail"))).toEqual(["sales_paise", "paid", "first_chats", "hot", "calls", "bookings"]);
  });

  it("puts Chats and Hot first for education and real estate", () => {
    expect(keys(orderOverviewCards(SENT, "Real Estate"))).toEqual(["first_chats", "hot", "bookings", "paid", "sales_paise", "calls"]);
  });

  it("keeps today's order for Other, unknown or missing type", () => {
    for (const type of ["Other", "Agency", "", null, undefined]) {
      expect(orderOverviewCards(SENT, type)).toBe(SENT);
    }
  });

  it("never drops or adds a card, and does not change the input", () => {
    const before = keys(SENT);
    const sparse = [{ key: "hot" }, { key: "new_buyers" }, { key: "calls" }];
    expect(keys(orderOverviewCards(sparse, "Clinic")).sort()).toEqual(["calls", "hot", "new_buyers"]);
    orderOverviewCards(SENT, "Clinic");
    expect(keys(SENT)).toEqual(before);
  });

  it("keeps the backend order among cards that have no preference", () => {
    const cards = ["calls", "cost_per_chat_paise", "new_buyers"].map((key) => ({ key }));
    expect(keys(orderOverviewCards(cards, "Clinic"))).toEqual(["calls", "cost_per_chat_paise", "new_buyers"]);
  });
});
