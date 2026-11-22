import { describe, expect, it } from "vitest";
import {
  alertHref,
  alertKindFor,
  canSeeAlert,
  chipCounts,
  cleanMessage,
  filterByChip,
  normaliseChatLink,
  safeInternalPath,
  timeAgo,
  unreadCount,
  visibleChips,
  type BellAlert,
} from "./alertKinds";

const mk = (type: string, extra: Partial<BellAlert> = {}): BellAlert => ({
  id: type,
  type,
  title: "t",
  message: "m",
  is_read: false,
  created_at: "2026-11-22T10:00:00Z",
  ...extra,
});

const KNOWN = [
  "lead_assigned", "lead_reassigned", "lead_replied", "callback_taken_over", "callback_reminder", "callback_due",
  "callback_late", "callback_claimable", "leads_waiting", "sim_call_handoff", "milestone_achieved",
  "call_alert_no_answer", "call_alerts_summary", "sms_low_balance", "batch_expiry", "day_closing", "quote_accepted",
  "purchase_order", "supplier_message", "unmarked_bookings", "brain_digest", "scheduled_template_failed",
  "intake_trigger_failed", "system_error", "handover_new", "deal_double_payment", "intake_double_payment",
  "intake_paid", "intake_bridge_auth_failed", "intake_astro_push_failed", "intake_reply_undelivered", "lead_hot",
];

describe("alertKindFor", () => {
  it("knows every type in use (none fall to the unknown bucket by accident)", () => {
    for (const t of KNOWN) {
      const k = alertKindFor(t);
      expect(k.module, t).not.toBe("Alerts");
    }
  });

  it("maps the contract's categories and buttons", () => {
    for (const t of ["lead_replied", "lead_assigned", "handover_new", "lead_hot"]) {
      expect(alertKindFor(t).category).toBe("needs_you");
      expect(alertKindFor(t).action?.label).toBe("Open chat");
    }
    for (const t of ["callback_taken_over", "callback_reminder", "callback_due", "callback_late", "callback_claimable", "leads_waiting", "call_alerts_summary", "call_alert_no_answer"]) {
      expect(alertKindFor(t).category, t).toBe("calls");
    }
    expect(alertKindFor("callback_due").action?.label).toBe("Call back list");
    expect(alertKindFor("leads_waiting").action?.label).toBe("Open");
    for (const t of ["deal_double_payment", "intake_double_payment", "intake_paid", "quote_accepted", "day_closing", "purchase_order"]) {
      expect(alertKindFor(t).category, t).toBe("money");
      expect(alertKindFor(t).action?.label).toBe("See");
    }
    expect(alertKindFor("batch_expiry")).toMatchObject({ category: "stock", action: { label: "See batches" } });
    expect(alertKindFor("sms_low_balance")).toMatchObject({ category: "other", action: { label: "Top up" } });
    for (const t of ["scheduled_template_failed", "system_error", "intake_trigger_failed", "intake_bridge_auth_failed", "intake_astro_push_failed", "intake_reply_undelivered"]) {
      expect(alertKindFor(t).category, t).toBe("other");
      expect(alertKindFor(t).action?.label).toBe("See");
    }
  });

  it("puts a type it does not know in other, with no button", () => {
    const k = alertKindFor("something_new");
    expect(k.category).toBe("other");
    expect(k.action).toBeNull();
    expect(alertHref(mk("something_new", { url: "/dashboard/x" }))).toBeNull();
  });
});

describe("alertHref fallback order", () => {
  it("uses the stored link first (non-chat alerts)", () => {
    expect(alertHref(mk("batch_expiry", { url: "/dashboard/catalog?tab=batches&x=1" }))).toBe("/dashboard/catalog?tab=batches&x=1");
  });

  it("chat alerts prefer the [lead_id:] tag over a stored link", () => {
    const n = mk("lead_replied", { url: "/dashboard/conversations?lead=A", message: "x [lead_id:B]" });
    expect(alertHref(n)).toBe("/dashboard/conversations?lead=B");
    const sup = mk("supplier_message", { url: "/dashboard/conversations?lead=L7", message: "Hi [lead_id:L7]" });
    expect(alertHref(sup)).toBe("/dashboard/conversations?lead=L7");
  });

  it("chat alerts use the stored link when there is no tag", () => {
    expect(alertHref(mk("lead_hot", { url: "/dashboard/conversations?lead=A" }))).toBe("/dashboard/conversations?lead=A");
  });

  it("rewrites a ?lead_id= chat link to the ?lead= the Chats page reads", () => {
    expect(normaliseChatLink("/dashboard/conversations?lead_id=L1")).toBe("/dashboard/conversations?lead=L1");
    expect(normaliseChatLink("/dashboard/conversations?x=1&lead_id=L1#top")).toBe("/dashboard/conversations?lead=L1&x=1#top");
    expect(normaliseChatLink("/dashboard/conversations?lead=L1")).toBe("/dashboard/conversations?lead=L1");
    expect(normaliseChatLink("/dashboard/sms?lead_id=1")).toBe("/dashboard/sms?lead_id=1");
    expect(alertHref(mk("lead_hot", { url: "/dashboard/conversations?lead_id=L8" }))).toBe("/dashboard/conversations?lead=L8");
  });

  it("then the type's own page", () => {
    expect(alertHref(mk("batch_expiry"))).toBe("/dashboard/catalog?tab=batches");
    expect(alertHref(mk("day_closing", { message: "[lead_id:Z]" }))).toBe("/dashboard/deals/day-closing");
    expect(alertHref(mk("sms_low_balance"))).toBe("/dashboard/sms");
  });

  it("then the [lead_id:] tag, as the bell did before", () => {
    expect(alertHref(mk("lead_replied", { message: "Asha replied [lead_id:L1]" }))).toBe("/dashboard/conversations?lead=L1");
    expect(alertHref(mk("handover_new", { message: "Ravi [lead_id:L2]" }))).toBe("/dashboard/conversations?lead=L2");
    expect(alertHref(mk("lead_assigned", { message: "New [lead_id:L3]" }))).toBe("/dashboard/telecalling?lead_id=L3");
    expect(alertHref(mk("sim_call_handoff", { message: "x [lead_id:L4]" }))).toBe("/dashboard/telecalling?lead_id=L4");
  });

  it("then the chats page for chat alerts, else nothing", () => {
    expect(alertHref(mk("lead_replied"))).toBe("/dashboard/conversations");
    expect(alertHref(mk("sim_call_handoff"))).toBe("/dashboard/telecalling");
  });

  it("ignores stored links that leave the site", () => {
    expect(safeInternalPath("https://evil.example/x")).toBeNull();
    expect(safeInternalPath("//evil.example")).toBeNull();
    expect(safeInternalPath("/\\evil")).toBeNull();
    expect(safeInternalPath("/\t/evil.com")).toBeNull();
    expect(safeInternalPath("/\n/evil.com")).toBeNull();
    expect(safeInternalPath("/dash board")).toBeNull();
    expect(safeInternalPath("/a\u0000b")).toBeNull();
    expect(safeInternalPath("/dashboard/sms?x=1")).toBe("/dashboard/sms?x=1");
    expect(safeInternalPath("")).toBeNull();
    expect(safeInternalPath(null)).toBeNull();
    expect(alertHref(mk("batch_expiry", { url: "https://evil.example" }))).toBe("/dashboard/catalog?tab=batches");
  });

  it("call_alert_<x> opens the needs-attention list", () => {
    expect(alertHref(mk("call_alert_no_answer"))).toBe("/dashboard/telecalling#needs-attention");
  });
});

describe("chips", () => {
  const items = [mk("lead_replied"), mk("lead_hot"), mk("day_closing"), mk("callback_due"), mk("system_error")];

  it("counts per chip; All counts everything, other kinds only in All", () => {
    expect(chipCounts(items)).toEqual({ all: 5, needs_you: 2, money: 1, stock: 0, calls: 1 });
  });

  it("hides a chip with nothing in the last 7 days", () => {
    expect(visibleChips(items).map((c) => c.key)).toEqual(["all", "needs_you", "money", "calls"]);
    expect(visibleChips([]).map((c) => c.key)).toEqual(["all"]);
    expect(visibleChips([mk("batch_expiry")]).map((c) => c.key)).toEqual(["all", "stock"]);
  });

  it("filters by chip", () => {
    expect(filterByChip(items, "all")).toHaveLength(5);
    expect(filterByChip(items, "needs_you").map((n) => n.type)).toEqual(["lead_replied", "lead_hot"]);
    expect(filterByChip(items, "stock")).toEqual([]);
  });

  it("counts unread", () => {
    expect(unreadCount([mk("a"), mk("b", { is_read: true }), mk("c")])).toBe(2);
  });
});

describe("money alerts need orders access", () => {
  it("hides money from people without deals.view, never from the owner", () => {
    expect(canSeeAlert(mk("day_closing"), { isOwner: false, permissions: ["leads.view"] })).toBe(false);
    expect(canSeeAlert(mk("day_closing"), { isOwner: false, permissions: ["deals.view"] })).toBe(true);
    expect(canSeeAlert(mk("day_closing"), { isOwner: false, permissions: ["deals.manage"] })).toBe(true);
    expect(canSeeAlert(mk("day_closing"), { isOwner: true, permissions: [] })).toBe(true);
    expect(canSeeAlert(mk("lead_replied"), { isOwner: false, permissions: [] })).toBe(true);
  });
});

describe("text helpers", () => {
  it("strips the internal tags", () => {
    expect(cleanMessage("Asha replied [lead_id:abc] [handover_id:9]")).toBe("Asha replied");
  });

  it("says how long ago in plain words", () => {
    const now = new Date("2026-11-22T12:00:00Z");
    expect(timeAgo("2026-11-22T11:59:40Z", now)).toBe("just now");
    expect(timeAgo("2026-11-22T11:58:00Z", now)).toBe("2 min ago");
    expect(timeAgo("2026-11-22T11:00:00Z", now)).toBe("1 hour ago");
    expect(timeAgo("2026-11-22T09:00:00Z", now)).toBe("3 hours ago");
    expect(timeAgo("2026-11-21T10:00:00Z", now)).toBe("yesterday");
    expect(timeAgo("2026-11-18T12:00:00Z", now)).toBe("4 days ago");
    expect(timeAgo("not a date", now)).toBe("");
  });
});
