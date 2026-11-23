import { describe, expect, it } from "vitest";
import {
  averageText,
  bookingStatusWords,
  buildLeadsQuery,
  campaignHrefForGroup,
  cleanTag,
  describeCallingResult,
  describeTagResult,
  eventMatchesChip,
  feedbackCostText,
  feedbackTemplateStatus,
  followUpHrefForGroup,
  isDontCallRow,
  lastDaysRange,
  looksLikePhone,
  normalizeTagList,
  parseTagInput,
  percentText,
  pickedGroupName,
  refundMethodWords,
  starsText,
  telHref,
} from "./customersApi";

describe("buildLeadsQuery", () => {
  it("keeps every old filter and adds only, came_from and tag", () => {
    const qs = buildLeadsQuery({
      segment: "A", buyer: true, bought: "repeat", search: "priya", only: "leads", came_from: "qr", tag: " VIP ",
      page: 2, limit: 25, sort: "urgent",
    });
    expect(qs.get("segment")).toBe("A");
    expect(qs.get("buyer")).toBe("true");
    expect(qs.get("bought")).toBe("repeat");
    expect(qs.get("search")).toBe("priya");
    expect(qs.get("only")).toBe("leads");
    expect(qs.get("came_from")).toBe("qr");
    expect(qs.get("tag")).toBe("VIP");
    expect(qs.get("page")).toBe("2");
    expect(qs.get("limit")).toBe("25");
    expect(qs.get("sort")).toBe("urgent");
  });

  it("leaves out empty filters and 'all' for came_from", () => {
    expect(buildLeadsQuery({ came_from: "all", tag: "  ", search: "" }).toString()).toBe("");
  });

  it("caps the page size at 200", () => {
    expect(buildLeadsQuery({ limit: 5000 }).get("limit")).toBe("200");
    expect(buildLeadsQuery({ limit: 0 }).get("limit")).toBe("1");
  });
});

describe("tags", () => {
  it("tidies one tag and cuts it at 30 characters", () => {
    expect(cleanTag("  big   spender ")).toBe("big spender");
    expect(cleanTag("   ")).toBeNull();
    expect(cleanTag("x".repeat(45))).toHaveLength(30);
  });

  it("splits typed tags on commas, drops repeats in any case and keeps the first spelling", () => {
    expect(parseTagInput("VIP, diwali ,vip,, Diwali, new")).toEqual(["VIP", "diwali", "new"]);
    expect(parseTagInput("")).toEqual([]);
  });

  it("reads the tag list however the backend wraps it", () => {
    expect(normalizeTagList([{ tag: "VIP", count: 4 }])).toEqual([{ tag: "VIP", count: 4 }]);
    expect(normalizeTagList({ tags: [{ name: "Diwali", count: 2 }, "new"] })).toEqual([
      { tag: "Diwali", count: 2 },
      { tag: "new", count: 0 },
    ]);
    expect(normalizeTagList({ data: [{ tag: "a", count: 1 }] })).toEqual([{ tag: "a", count: 1 }]);
    expect(normalizeTagList(null)).toEqual([]);
    expect(normalizeTagList({ tags: "nope" })).toEqual([]);
  });

  it("says what was added and what was skipped", () => {
    expect(describeTagResult("add", { added: 12, skipped_limit: 0 })).toBe("Added 12 tags");
    expect(describeTagResult("add", { added: 1 })).toBe("Added 1 tag");
    expect(describeTagResult("add", { added: 9, skipped_limit: 2 })).toBe(
      "Added 9 tags. 2 skipped: 10 tags is the most one person can have.",
    );
    expect(describeTagResult("remove", { removed: 3 })).toBe("Removed 3 tags");
  });
});

describe("send to calling", () => {
  const base = { added: 0, already: 0, said_stop: 0, bought: 0, closed: 0, not_found: 0, no_callers: false };

  it("writes the result line the screen shows", () => {
    expect(describeCallingResult({ ...base, added: 18, said_stop: 3, bought: 2, already: 4 })).toBe(
      "18 sent to calling · 3 said stop · 2 already bought · 4 already with a caller",
    );
  });

  it("leaves out zero parts and counts people who cannot be called", () => {
    expect(describeCallingResult({ ...base, added: 5 })).toBe("5 sent to calling");
    expect(describeCallingResult({ ...base, closed: 1, not_found: 2 })).toBe("0 sent to calling · 3 can't be called");
  });
});

describe("links to other screens", () => {
  it("opens Reach and the follow-up builder with the group picked", () => {
    expect(campaignHrefForGroup("g 1")).toBe("/dashboard/outbound-leads?group=g%201");
    expect(followUpHrefForGroup("abc")).toBe("/dashboard/leads?tab=follow-ups&group=abc");
  });
});

describe("Don't call rows on the Said stop list", () => {
  it("spots them by source or by the flag, but not real Said-stop people", () => {
    expect(isDontCallRow({ source: "do_not_call" })).toBe(true);
    expect(isDontCallRow({ do_not_call: true, opted_out_at: null, source: null })).toBe(true);
    expect(isDontCallRow({ do_not_call: true, opted_out_at: "2026-11-01", source: "call" })).toBe(false);
    expect(isDontCallRow({ source: "stop_reply" })).toBe(false);
  });
});

describe("feedback words", () => {
  it("names the star message status", () => {
    expect(feedbackTemplateStatus("APPROVED")).toEqual({ label: "Approved", tone: "good" });
    expect(feedbackTemplateStatus("pending").label).toBe("Waiting for Meta");
    expect(feedbackTemplateStatus("REJECTED").label).toBe("Turned down");
    expect(feedbackTemplateStatus(null).label).toBe("Not set up");
    expect(feedbackTemplateStatus("weird").tone).toBe("none");
  });

  it("shows the price per message with two decimals, falling back to 0.86", () => {
    expect(feedbackCostText(0.8631)).toBe("about ₹0.86 per message");
    expect(feedbackCostText(undefined)).toBe("about ₹0.86 per message");
    expect(feedbackCostText(1.2)).toBe("about ₹1.20 per message");
  });

  it("formats stars, averages and percentages", () => {
    expect(starsText(3)).toBe("⭐⭐⭐ 3");
    expect(starsText(null)).toBe("No rating");
    expect(starsText(9)).toBe("⭐⭐⭐⭐⭐ 5");
    expect(averageText(4.26)).toBe("4.3");
    expect(averageText(null)).toBe("—");
    expect(percentText(61.6)).toBe("62%");
    expect(percentText(null)).toBe("—");
  });

  it("builds a tel: link or nothing", () => {
    expect(telHref("919876543210")).toBe("tel:+919876543210");
    expect(telHref("+91 98765 43210")).toBe("tel:+919876543210");
    expect(telHref(null)).toBeNull();
    expect(telHref("12")).toBeNull();
  });

  it("gives the last N days in India time, today included", () => {
    // 2026-11-23 20:00 UTC is already 24 Nov 01:30 in India.
    const now = new Date("2026-11-23T20:00:00Z");
    expect(lastDaysRange(1, now)).toEqual({ from: "2026-11-24", to: "2026-11-24" });
    expect(lastDaysRange(30, now)).toEqual({ from: "2026-10-26", to: "2026-11-24" });
  });
});

describe("customer page events", () => {
  it("filters the timeline by chip; Visits covers bookings, visits and no-shows", () => {
    expect(eventMatchesChip("order", "all")).toBe(true);
    expect(eventMatchesChip("refund", "refund")).toBe(true);
    expect(eventMatchesChip("refund", "order")).toBe(false);
    for (const kind of ["visit", "no_show", "booking"]) expect(eventMatchesChip(kind, "visit")).toBe(true);
    expect(eventMatchesChip("feedback", "visit")).toBe(false);
    expect(eventMatchesChip("feedback", "feedback")).toBe(true);
  });

  it("puts refund methods and booking statuses in plain words", () => {
    expect(refundMethodWords("razorpay")).toBe("online");
    expect(refundMethodWords("credit_note")).toBe("credit note");
    expect(refundMethodWords("store_credit")).toBe("store credit");
    expect(refundMethodWords(null)).toBeNull();
    expect(bookingStatusWords("no_show")).toBe("didn't come");
    expect(bookingStatusWords("x")).toBeNull();
  });
});

describe("Picked people become a group", () => {
  it("names the group by India time and varies the name when it is taken", () => {
    const at = new Date("2026-11-23T10:15:30Z"); // 3:45:30 pm IST
    expect(pickedGroupName(at, 0)).toBe("Picked · 23 Nov, 3:45 pm");
    expect(pickedGroupName(at, 1)).toBe("Picked · 23 Nov, 3:45:30 pm");
    expect(pickedGroupName(at, 2)).toMatch(/^Picked · 23 Nov, 3:45:30 pm .+$/);
    expect(pickedGroupName(at, 0).length).toBeLessThanOrEqual(80);
  });
});

describe("looksLikePhone", () => {
  it("accepts numbers however they are typed and rejects words and short digits", () => {
    expect(looksLikePhone("98765 43210")).toBe(true);
    expect(looksLikePhone("+91 98765-43210")).toBe(true);
    expect(looksLikePhone("(044) 2345 6789")).toBe(true);
    expect(looksLikePhone("priya")).toBe(false);
    expect(looksLikePhone("12345")).toBe(false);
    expect(looksLikePhone("98765abc43210")).toBe(false);
  });
});
