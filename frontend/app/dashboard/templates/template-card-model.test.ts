import { describe, expect, it } from "vitest";
import type { Template } from "./types";
import { cardNote, statusLabel, timeAgo, usedIn } from "./template-card-model";
import { NEEDS_FIX, NO_FILTERS, filterTemplates } from "./template-filters";
import { prefillFromTemplate, safeTemplateName } from "./template-prefill";

const NOW = Date.parse("2026-11-23T12:00:00Z");
const base: Template = { id: "a", name: "promo", category: "MARKETING", language: "ta", body_text: "Hi {{1}}", status: "APPROVED" };

describe("timeAgo", () => {
  it("speaks in minutes, hours, days", () => {
    expect(timeAgo("2026-11-23T11:40:00Z", NOW)).toBe("20 min ago");
    expect(timeAgo("2026-11-23T09:00:00Z", NOW)).toBe("3 hours ago");
    expect(timeAgo("2026-11-22T12:00:00Z", NOW)).toBe("1 day ago");
    expect(timeAgo(undefined, NOW)).toBe("");
  });
});

describe("cardNote", () => {
  it("warns on a staff alert filed as Marketing before anything else", () => {
    const usage = [{ area: "staff_alert", label: "Alert to staff", href: "/x" }];
    expect(cardNote({ ...base, status: "PENDING" }, usage, NOW)?.kind).toBe("staff-marketing");
  });
  it("says when a pending template went to Meta", () => {
    expect(cardNote({ ...base, status: "PENDING", submitted_at: "2026-11-23T11:40:00Z" }, [], NOW)).toEqual({
      kind: "pending",
      text: "Sent to Meta 20 min ago · usually under 1 hour",
    });
  });
  it("gives the rejection reason in plain words", () => {
    const n = cardNote({ ...base, status: "REJECTED", rejection_reason: "INCORRECT_CATEGORY" }, [], NOW);
    expect(n?.kind).toBe("rejected");
    expect(n && "text" in n ? n.text : "").toContain("type (Marketing or Utility)");
  });
  it("is empty for an approved template with nothing wrong", () => {
    expect(cardNote(base, [], NOW)).toBeNull();
  });
});

describe("usedIn", () => {
  it("shows the first live place and how many more", () => {
    const u = usedIn([
      { area: "reach", label: "Reach · 1 campaign", href: "/r" },
      { area: "commerce", label: "Commerce", href: "/c" },
    ]);
    expect(u).toEqual({ kind: "live", icon: "📣", label: "Reach · 1 campaign", more: 1 });
  });
  it("names where an ended template was", () => {
    expect(usedIn([{ area: "reach", label: "was in Reach · ended", href: "/r", ended: true }])).toEqual({ kind: "ended", label: "Was in Reach · ended" });
  });
  it("says not used yet", () => {
    expect(usedIn(undefined)).toEqual({ kind: "none" });
  });
});

describe("statusLabel", () => {
  it("uses plain words", () => {
    expect(statusLabel("PENDING")).toBe("Pending Review");
    expect(statusLabel("DISABLED")).toBe("Turned off");
  });
});

describe("Rejected / Paused filter", () => {
  it("keeps rejected, paused and turned-off templates only", () => {
    const list = ["APPROVED", "REJECTED", "PAUSED", "DISABLED", "PENDING"].map((status, i) => ({ ...base, id: String(i), status }) as Template);
    expect(filterTemplates(list, { ...NO_FILTERS, status: NEEDS_FIX }).map((t) => t.status)).toEqual(["REJECTED", "PAUSED", "DISABLED"]);
  });
});

describe("prefill", () => {
  it("makes a Meta-safe copy name", () => {
    expect(safeTemplateName("Diwali Offer 2026!")).toBe("diwali_offer_2026");
    expect(prefillFromTemplate(base).name).toBe("promo_copy");
  });
  it("can turn a staff alert into a Utility copy", () => {
    const p = prefillFromTemplate({ ...base, buttons: [{ type: "URL", text: "Pay", url: "https://x" }] }, { category: "UTILITY", suffix: "utility" });
    expect(p.category).toBe("UTILITY");
    expect(p.name).toBe("promo_utility");
    expect(p.buttons).toHaveLength(1);
  });
});
