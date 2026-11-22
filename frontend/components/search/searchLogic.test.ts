import { describe, expect, it } from "vitest";
import {
  buildSections, canSearch, canUseSearch, flatRows, highlightParts, isFreshAnswer, isSlashShortcut, isTypingTarget, nextFocusIndex, nextIndex, shortDate,
} from "./searchLogic";

const key = (over: Record<string, unknown> = {}) => ({ key: "/", target: { tagName: "BODY" }, ...over });

describe("the / shortcut", () => {
  it("fires from the page body", () => {
    expect(isSlashShortcut(key())).toBe(true);
    expect(isSlashShortcut(key({ target: null }))).toBe(true);
  });
  it("is ignored while typing in an input, textarea, select or editable box", () => {
    expect(isSlashShortcut(key({ target: { tagName: "INPUT" } }))).toBe(false);
    expect(isSlashShortcut(key({ target: { tagName: "textarea" } }))).toBe(false);
    expect(isSlashShortcut(key({ target: { tagName: "SELECT" } }))).toBe(false);
    expect(isSlashShortcut(key({ target: { tagName: "DIV", isContentEditable: true } }))).toBe(false);
    expect(isSlashShortcut(key({ target: { tagName: "DIV", getAttribute: () => "true" } }))).toBe(false);
  });
  it("is ignored with a modifier, during IME composition, after preventDefault, or for other keys", () => {
    expect(isSlashShortcut(key({ ctrlKey: true }))).toBe(false);
    expect(isSlashShortcut(key({ metaKey: true }))).toBe(false);
    expect(isSlashShortcut(key({ altKey: true }))).toBe(false);
    expect(isSlashShortcut(key({ isComposing: true }))).toBe(false);
    expect(isSlashShortcut(key({ defaultPrevented: true }))).toBe(false);
    expect(isSlashShortcut(key({ key: "k" }))).toBe(false);
  });
  it("treats a plain div as not typing", () => {
    expect(isTypingTarget({ tagName: "DIV", getAttribute: () => null })).toBe(false);
    expect(isTypingTarget(undefined)).toBe(false);
  });
});

describe("canSearch and canUseSearch", () => {
  it("needs 2 to 60 characters after trimming", () => {
    expect(canSearch("a")).toBe(false);
    expect(canSearch("  a ")).toBe(false);
    expect(canSearch("ab")).toBe(true);
    expect(canSearch("x".repeat(60))).toBe(true);
    expect(canSearch("x".repeat(61))).toBe(false);
  });
  it("shows to owners and to anyone with a searched area, not to people with none", () => {
    expect(canUseSearch(null, ["leads.view"])).toBe(false);
    expect(canUseSearch("owner", [])).toBe(true);
    expect(canUseSearch("staff", ["deals.manage"])).toBe(true);
    expect(canUseSearch("staff", ["conversations.reply"])).toBe(true);
    expect(canUseSearch("staff", ["settings.view"])).toBe(false);
  });
});

describe("buildSections", () => {
  const groups = [
    { key: "chats", title: "Chats", items: [{ lead_id: "L1", name: "Priya", snippet: "silk saree", channel: "whatsapp", date: "2026-11-12T08:00:00+00:00" }] },
    { key: "customers", title: "Customers", items: [{ id: "L1", name: "Priya Raman", phone: "+91636", detail: "Hot", href: "/dashboard/leads/L1" }] },
    { key: "items", title: "Items", items: [{ id: "I1", name: "Silk Saree", detail: "₹10,500 · 3 in stock" }] },
    { key: "orders", title: "Orders", items: [{ id: "D1", label: "D-0012 · Priya", detail: "₹10,500 · paid · 12 Nov" }] },
    { key: "mystery", title: "?", items: [{ id: "z" }] },
  ];

  it("orders the groups Customers, Orders & Bills, Items, Chats whatever order they arrive in", () => {
    expect(buildSections(groups).map((s) => s.heading)).toEqual(["CUSTOMERS", "ORDERS & BILLS", "ITEMS", "CHATS"]);
  });
  it("drops empty and unknown groups", () => {
    const only = buildSections([{ key: "items", title: "", items: [] }, { key: "x", title: "", items: [{ id: "1" }] }]);
    expect(only).toEqual([]);
    expect(buildSections(undefined)).toEqual([]);
  });
  it("builds the rows with their pages", () => {
    const rows = flatRows(buildSections(groups));
    expect(rows.map((r) => r.href)).toEqual([
      "/dashboard/leads/L1", "/dashboard/deals/orders/D1", "/dashboard/catalog/items/I1", "/dashboard/conversations?lead=L1",
    ]);
    expect(rows[0]).toMatchObject({ title: "Priya Raman", subtitle: "+91636 · Hot" });
    expect(rows[3]).toMatchObject({ title: "Priya", subtitle: "silk saree", meta: "WhatsApp · 12 Nov" });
  });
  it("ignores an address that leaves the app", () => {
    const rows = flatRows(buildSections([{ key: "customers", title: "", items: [{ id: "L9", name: "A", href: "https://evil.example/x" }] }]));
    expect(rows[0].href).toBe("/dashboard/leads/L9");
  });
  it("shows at most 5 rows per group and keeps option ids unique", () => {
    const many = Array.from({ length: 8 }, (_, i) => ({ id: `L${i}`, name: `N${i}` }));
    const rows = flatRows(buildSections([{ key: "customers", title: "", items: many }]));
    expect(rows).toHaveLength(5);
    expect(new Set(rows.map((r) => r.id)).size).toBe(5);
  });
});

describe("nextIndex", () => {
  it("starts at the top going down and the bottom going up, then wraps", () => {
    expect(nextIndex(-1, 1, 3)).toBe(0);
    expect(nextIndex(-1, -1, 3)).toBe(2);
    expect(nextIndex(2, 1, 3)).toBe(0);
    expect(nextIndex(0, -1, 3)).toBe(2);
    expect(nextIndex(1, 1, 3)).toBe(2);
    expect(nextIndex(0, 1, 0)).toBe(-1);
  });
});

describe("highlightParts", () => {
  it("marks every matching word, ignoring case", () => {
    expect(highlightParts("Priya Raman", "priya ram")).toEqual([
      { text: "Priya", match: true }, { text: " ", match: false }, { text: "Ram", match: true }, { text: "an", match: false },
    ]);
  });
  it("marks digits inside a phone number", () => {
    expect(highlightParts("+916369781582", "6369")).toEqual([
      { text: "+91", match: false }, { text: "6369", match: true }, { text: "781582", match: false },
    ]);
  });
  it("takes regex characters literally", () => {
    expect(highlightParts("Price (new)", "(new)")).toEqual([{ text: "Price ", match: false }, { text: "(new)", match: true }]);
    expect(highlightParts("a.b", ".")).toEqual([{ text: "a", match: false }, { text: ".", match: true }, { text: "b", match: false }]);
  });
  it("returns the whole text when nothing matches, and nothing for empty text", () => {
    expect(highlightParts("Silk", "zzz")).toEqual([{ text: "Silk", match: false }]);
    expect(highlightParts("", "x")).toEqual([]);
  });
  it("ignores a leading # so '#12' marks the 12 in an order number", () => {
    expect(highlightParts("D-0012", "#12")).toEqual([{ text: "D-00", match: false }, { text: "12", match: true }]);
  });
});

describe("shortDate", () => {
  it("is the Indian-time day and month", () => {
    expect(shortDate("2026-11-12T08:00:00+00:00")).toBe("12 Nov");
    expect(shortDate("2026-11-12T20:00:00+00:00")).toBe("13 Nov"); // 1:30 AM next day in India
    expect(shortDate("nope")).toBe("");
    expect(shortDate(null)).toBe("");
  });
});

describe("isFreshAnswer (Enter guard)", () => {
  it("is true only when loading is done and the answer is for the current trimmed query", () => {
    expect(isFreshAnswer("done", "priya", "priya")).toBe(true);
    expect(isFreshAnswer("done", "priya", "  priya ")).toBe(true);
    expect(isFreshAnswer("done", "priya", "priyan")).toBe(false); // typed more, answer is stale
    expect(isFreshAnswer("loading", "priya", "priya")).toBe(false);
    expect(isFreshAnswer("error", "priya", "priya")).toBe(false);
    expect(isFreshAnswer("idle", "", "")).toBe(false);
  });
});

describe("nextFocusIndex (Tab trap)", () => {
  it("wraps forward and backward through the focusable things", () => {
    expect(nextFocusIndex(0, 2, false)).toBe(1);
    expect(nextFocusIndex(1, 2, false)).toBe(0);
    expect(nextFocusIndex(0, 2, true)).toBe(1);
    expect(nextFocusIndex(1, 2, true)).toBe(0);
    expect(nextFocusIndex(-1, 2, false)).toBe(0);
    expect(nextFocusIndex(-1, 2, true)).toBe(1);
    expect(nextFocusIndex(0, 0, false)).toBe(-1);
  });
});
