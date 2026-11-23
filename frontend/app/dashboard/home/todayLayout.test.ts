import { describe, expect, it } from "vitest";
import type { HomeBoxKey } from "@/lib/api";
import {
  BOX_KEYS,
  BOX_META,
  COMING_SOON_BOX_KEYS,
  LIST_KEYS,
  LIST_LABELS,
  MAX_BOXES,
  addBox,
  boxSub,
  buildSavePayload,
  canAddBox,
  formatBoxValue,
  formatRupees,
  isBoxKey,
  isLoss,
  listIsOn,
  listsFromLayout,
  moveBox,
  removeBox,
  resolveBoxes,
  starsText,
  waitingFor,
} from "./todayLayout";

const ALL_LISTS_ON = { waiting: true, low_stock: true, todays_feedback: true };

const today = {
  available: ["money_in_today", "new_enquiries_today", "hot_waiting", "to_collect", "callbacks_today", "orders_pending", "ads_today"] as HomeBoxKey[],
  defaults: ["money_in_today", "new_enquiries_today", "hot_waiting", "to_collect", "callbacks_today", "orders_pending"] as HomeBoxKey[],
};

describe("resolveBoxes", () => {
  it("uses the suggested set when there is no saved layout", () => {
    expect(resolveBoxes(null, today)).toEqual(today.defaults);
    expect(resolveBoxes({ boxes: null }, today)).toEqual(today.defaults);
    expect(resolveBoxes(undefined, today)).toEqual(today.defaults);
  });

  it("keeps the saved order", () => {
    expect(resolveBoxes({ boxes: ["ads_today", "money_in_today", "hot_waiting"] }, today)).toEqual([
      "ads_today",
      "money_in_today",
      "hot_waiting",
    ]);
  });

  it("drops a saved box the person can no longer see", () => {
    expect(resolveBoxes({ boxes: ["low_stock", "money_in_today", "won_month", "hot_waiting"] }, today)).toEqual([
      "money_in_today",
      "hot_waiting",
    ]);
  });

  it("falls back to the suggested set when nothing saved is still available", () => {
    expect(resolveBoxes({ boxes: ["low_stock", "won_month"] }, today)).toEqual(today.defaults);
    expect(resolveBoxes({ boxes: [] }, today)).toEqual(today.defaults);
  });

  it("ignores unknown and duplicate keys", () => {
    const boxes = ["money_in_today", "renewals_due", "money_in_today", "hot_waiting"] as unknown as HomeBoxKey[];
    expect(resolveBoxes({ boxes }, today)).toEqual(["money_in_today", "hot_waiting"]);
  });

  it("shows fewer than 6 defaults when fewer are available", () => {
    const few = { available: ["hot_waiting"] as HomeBoxKey[], defaults: ["hot_waiting"] as HomeBoxKey[] };
    expect(resolveBoxes(null, few)).toEqual(["hot_waiting"]);
  });

  it("returns nothing before the data has loaded", () => {
    expect(resolveBoxes(null, null)).toEqual([]);
  });
});

describe("max 12 guard", () => {
  const twelve = BOX_KEYS.slice(0, 11) as HomeBoxKey[];

  it("more boxes exist than one person can turn on: the cap is how many are ON, not how many exist", () => {
    expect(BOX_KEYS).toHaveLength(15);
    expect(MAX_BOXES).toBe(12);
    const eleven = BOX_KEYS.slice(0, 11);
    const full = [...eleven, "bookings_today"] as HomeBoxKey[];
    expect(addBox(eleven, "bookings_today")).toEqual(full);
    expect(addBox(full, "profit_month")).toEqual(full);
    expect(addBox(BOX_KEYS.slice(0, 12), "feedback_week")).toEqual(BOX_KEYS.slice(0, 12));
  });

  it("canAddBox turns false at 12", () => {
    expect(canAddBox(new Array(11).fill("x"))).toBe(true);
    expect(canAddBox(new Array(12).fill("x"))).toBe(false);
  });

  it("addBox refuses a 13th, a duplicate, and an unknown key", () => {
    const full = new Array(12).fill("money_in_today") as HomeBoxKey[];
    expect(addBox(full, "low_stock")).toEqual(full);
    expect(addBox(twelve, "money_in_today")).toEqual(twelve);
    expect(addBox(["hot_waiting"], "nope")).toEqual(["hot_waiting"]);
    expect(addBox(["hot_waiting"], "low_stock")).toEqual(["hot_waiting", "low_stock"]);
  });

  it("buildSavePayload never sends more than 12 or an unknown key", () => {
    const many = [...BOX_KEYS, ...BOX_KEYS, "profit_month"] as unknown as HomeBoxKey[];
    const payload = buildSavePayload(many, { waiting: true, low_stock: false, todays_feedback: true });
    expect(payload.boxes.length).toBeLessThanOrEqual(MAX_BOXES);
    expect(payload.boxes.every(isBoxKey)).toBe(true);
    expect(payload.lists).toEqual({ waiting: true, low_stock: false, todays_feedback: true });
  });
});

describe("Target this month box", () => {
  it("is a working box now", () => {
    expect(BOX_KEYS).toContain("target_month");
    expect(isBoxKey("target_month")).toBe(true);
    expect(BOX_META.target_month.label).toBe("Target this month");
    expect(COMING_SOON_BOX_KEYS).not.toContain("target_month");
  });

  it("can be added and saved like any other box", () => {
    expect(addBox([], "target_month")).toEqual(["target_month"]);
    expect(buildSavePayload(["target_month", "hot_waiting"], ALL_LISTS_ON).boxes).toEqual(["target_month", "hot_waiting"]);
  });

  it("is kept by resolveBoxes only when this person may see it", () => {
    const withTarget = { available: ["hot_waiting", "target_month"] as HomeBoxKey[], defaults: ["hot_waiting"] as HomeBoxKey[] };
    expect(resolveBoxes({ boxes: ["target_month", "hot_waiting"] as HomeBoxKey[] }, withTarget)).toEqual(["target_month", "hot_waiting"]);
    expect(resolveBoxes({ boxes: ["target_month", "hot_waiting"] as HomeBoxKey[] }, { available: ["hot_waiting"] as HomeBoxKey[], defaults: ["hot_waiting"] as HomeBoxKey[] })).toEqual(["hot_waiting"]);
  });

  it("shows money for the owner, a percent for the team, and Set a target when none", () => {
    expect(formatBoxValue({ value: 18_600_000, unit: "paise" })).toBe("₹1,86,000");
    expect(formatBoxValue({ value: 93, unit: "percent" })).toBe("93%");
    expect(formatBoxValue({ value: 0, unit: "set_target" })).toBe("Set a target");
  });
});

describe("coming-soon keys", () => {
  it("are never selectable", () => {
    expect(COMING_SOON_BOX_KEYS).toEqual(["renewals_due"]);
    for (const key of COMING_SOON_BOX_KEYS) {
      expect(isBoxKey(key)).toBe(false);
      expect(BOX_KEYS).not.toContain(key);
      expect(Object.keys(BOX_META)).not.toContain(key);
      expect(addBox([], key)).toEqual([]);
    }
  });

  it("are not kept by resolveBoxes even when a saved layout names them", () => {
    const boxes = ["renewals_due", "hot_waiting"] as unknown as HomeBoxKey[];
    expect(resolveBoxes({ boxes }, { available: ["hot_waiting"], defaults: ["hot_waiting"] })).toEqual(["hot_waiting"]);
  });
});

describe("reordering", () => {
  const list: HomeBoxKey[] = ["money_in_today", "hot_waiting", "to_collect"];
  it("moves down and up", () => {
    expect(moveBox(list, "money_in_today", 1)).toEqual(["hot_waiting", "money_in_today", "to_collect"]);
    expect(moveBox(list, "to_collect", -1)).toEqual(["money_in_today", "to_collect", "hot_waiting"]);
  });
  it("stays put at the ends and for a missing key", () => {
    expect(moveBox(list, "money_in_today", -1)).toEqual(list);
    expect(moveBox(list, "to_collect", 1)).toEqual(list);
    expect(moveBox(list, "low_stock", 1)).toEqual(list);
  });
  it("removes a box", () => {
    expect(removeBox(list, "hot_waiting")).toEqual(["money_in_today", "to_collect"]);
  });
});

describe("lists", () => {
  it("default on, off only when the layout says false", () => {
    expect(listIsOn(null, "waiting")).toBe(true);
    expect(listIsOn({ lists: null }, "low_stock")).toBe(true);
    expect(listIsOn({ lists: { waiting: false, low_stock: true, todays_feedback: true } }, "waiting")).toBe(false);
    expect(listIsOn({ lists: { waiting: false, low_stock: true, todays_feedback: true } }, "low_stock")).toBe(true);
  });
});

describe("rupees", () => {
  it("formats paise with Indian grouping", () => {
    expect(formatRupees(2465000)).toBe("₹24,650");
    expect(formatRupees(18640000)).toBe("₹1,86,400");
    expect(formatRupees(0)).toBe("₹0");
    expect(formatRupees(30050)).toBe("₹300.50");
    expect(formatRupees(null)).toBe("—");
  });
  it("formatBoxValue picks by unit", () => {
    expect(formatBoxValue({ value: 2770000, unit: "paise" })).toBe("₹27,700");
    expect(formatBoxValue({ value: 23, unit: "count" })).toBe("23");
  });
});

describe("waitingFor", () => {
  const now = new Date("2026-11-21T10:00:00Z").getTime();
  it("reads minutes, hours and days", () => {
    expect(waitingFor("2026-11-21T09:58:00Z", now)).toBe("2m");
    expect(waitingFor("2026-11-21T07:50:00Z", now)).toBe("2h 10m");
    expect(waitingFor("2026-11-18T10:00:00Z", now)).toBe("3d");
    expect(waitingFor("2026-11-21T10:00:00Z", now)).toBe("just now");
    expect(waitingFor(null, now)).toBe("");
  });
});

describe("Bookings today box", () => {
  it("is a working box now, not coming soon", () => {
    expect(BOX_KEYS).toContain("bookings_today");
    expect(isBoxKey("bookings_today")).toBe(true);
    expect(BOX_META.bookings_today.label).toBe("Bookings today");
    expect(COMING_SOON_BOX_KEYS).not.toContain("bookings_today");
  });
  it("is kept only when this person may see it", () => {
    const some = { available: ["hot_waiting", "bookings_today"] as HomeBoxKey[], defaults: ["hot_waiting"] as HomeBoxKey[] };
    expect(resolveBoxes({ boxes: ["bookings_today", "hot_waiting"] as HomeBoxKey[] }, some)).toEqual(["bookings_today", "hot_waiting"]);
    expect(resolveBoxes({ boxes: ["bookings_today", "hot_waiting"] as HomeBoxKey[] }, { available: ["hot_waiting"], defaults: ["hot_waiting"] })).toEqual(["hot_waiting"]);
  });
  it("saves like any other box and shows as a count", () => {
    expect(buildSavePayload(["bookings_today"], ALL_LISTS_ON).boxes).toEqual(["bookings_today"]);
    expect(formatBoxValue({ value: 7, unit: "count" })).toBe("7");
  });
});

describe("Profit this month box", () => {
  it("is a working money box, no longer coming soon", () => {
    expect(BOX_KEYS).toContain("profit_month");
    expect(isBoxKey("profit_month")).toBe(true);
    expect(BOX_META.profit_month.label).toBe("Profit this month");
    expect(BOX_META.profit_month.group).toBe("money");
    expect(COMING_SOON_BOX_KEYS).not.toContain("profit_month");
  });
  it("shows rupees like the other money boxes", () => {
    expect(formatBoxValue({ value: 4_800_000, unit: "paise" })).toBe("₹48,000");
  });
  it("shows a loss as a negative number with the word Loss", () => {
    expect(formatBoxValue({ value: -250_000, unit: "paise" })).toBe("-₹2,500");
    expect(formatRupees(-30050)).toBe("-₹300.50");
    expect(isLoss("profit_month", { value: -1 })).toBe(true);
    expect(isLoss("profit_month", { value: 0 })).toBe(false);
    expect(isLoss("to_collect", { value: -1 })).toBe(false);
    expect(boxSub("profit_month", { value: -250_000, sub: "Nov so far" })).toBe("Loss · Nov so far");
    expect(boxSub("profit_month", { value: 250_000, sub: "Nov so far" })).toBe("Nov so far");
  });
});

describe("Expenses today box", () => {
  it("is a working money box, no longer coming soon", () => {
    expect(BOX_KEYS).toContain("expenses_today");
    expect(BOX_META.expenses_today.label).toBe("Expenses today");
    expect(BOX_META.expenses_today.group).toBe("money");
    expect(COMING_SOON_BOX_KEYS).not.toContain("expenses_today");
    expect(formatBoxValue({ value: 120_000, unit: "paise" })).toBe("₹1,200");
    expect(formatBoxValue({ value: 0, unit: "paise" })).toBe("₹0");
  });
});

describe("Feedback this week box", () => {
  it("is a working box, no longer coming soon", () => {
    expect(BOX_KEYS).toContain("feedback_week");
    expect(BOX_META.feedback_week.label).toBe("Feedback this week");
    expect(COMING_SOON_BOX_KEYS).not.toContain("feedback_week");
    expect(COMING_SOON_BOX_KEYS).toContain("renewals_due");
  });
  it("shows the average with one decimal and a star", () => {
    expect(formatBoxValue({ value: 4.3, unit: "stars" })).toBe("4.3★");
    expect(formatBoxValue({ value: 5, unit: "stars" })).toBe("5.0★");
    expect(formatBoxValue({ value: 3.66, unit: "stars" })).toBe("3.7★");
  });
  it("shows a dash while nobody has answered", () => {
    expect(formatBoxValue({ value: null, unit: "stars" })).toBe("—");
    expect(formatBoxValue({ value: null, unit: "paise" })).toBe("—");
  });
  it("keeps the sub line as the server sent it", () => {
    expect(boxSub("feedback_week", { value: 4.3, sub: "12 answered · 2 unhappy open" })).toBe("12 answered · 2 unhappy open");
  });
  it("is kept by resolveBoxes only when this person may see it", () => {
    const some = { available: ["hot_waiting", "feedback_week"] as HomeBoxKey[], defaults: ["hot_waiting"] as HomeBoxKey[] };
    expect(resolveBoxes({ boxes: ["feedback_week", "hot_waiting"] as HomeBoxKey[] }, some)).toEqual(["feedback_week", "hot_waiting"]);
    expect(resolveBoxes({ boxes: ["feedback_week", "hot_waiting"] as HomeBoxKey[] }, { available: ["hot_waiting"], defaults: ["hot_waiting"] })).toEqual(["hot_waiting"]);
  });
});

describe("Today's feedback list", () => {
  it("can be switched on and off like the others, default on", () => {
    expect(LIST_KEYS).toContain("todays_feedback");
    expect(LIST_LABELS.todays_feedback).toBe("Today's feedback");
    expect(listIsOn(null, "todays_feedback")).toBe(true);
    expect(listIsOn({ lists: { waiting: true, low_stock: true, todays_feedback: false } }, "todays_feedback")).toBe(false);
  });
  it("an older saved layout without it still shows it", () => {
    const old = { lists: { waiting: false, low_stock: true } } as unknown as Parameters<typeof listsFromLayout>[0];
    expect(listsFromLayout(old)).toEqual({ waiting: false, low_stock: true, todays_feedback: true });
  });
  it("is saved with the layout", () => {
    expect(buildSavePayload(["hot_waiting"], { waiting: true, low_stock: true, todays_feedback: false }).lists).toEqual({
      waiting: true,
      low_stock: true,
      todays_feedback: false,
    });
  });
  it("draws stars as text", () => {
    expect(starsText(4)).toBe("★★★★☆");
    expect(starsText(1)).toBe("★☆☆☆☆");
    expect(starsText(9)).toBe("★★★★★");
    expect(starsText(-2)).toBe("☆☆☆☆☆");
  });
});
