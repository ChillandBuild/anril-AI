import { describe, expect, it } from "vitest";
import type { HomeBoxKey } from "@/lib/api";
import {
  BOX_KEYS,
  BOX_META,
  COMING_SOON_BOX_KEYS,
  MAX_BOXES,
  addBox,
  buildSavePayload,
  canAddBox,
  formatBoxValue,
  formatRupees,
  isBoxKey,
  listIsOn,
  moveBox,
  removeBox,
  resolveBoxes,
  waitingFor,
} from "./todayLayout";

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
    const boxes = ["money_in_today", "profit_month", "money_in_today", "hot_waiting"] as unknown as HomeBoxKey[];
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
  const twelve = BOX_KEYS.slice(0, 10) as HomeBoxKey[];

  it("only 10 working boxes exist, so 12 can never be reached with real keys", () => {
    expect(BOX_KEYS).toHaveLength(10);
    expect(MAX_BOXES).toBe(12);
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
    const payload = buildSavePayload(many, { waiting: true, low_stock: false });
    expect(payload.boxes.length).toBeLessThanOrEqual(MAX_BOXES);
    expect(payload.boxes.every(isBoxKey)).toBe(true);
    expect(payload.lists).toEqual({ waiting: true, low_stock: false });
  });
});

describe("coming-soon keys", () => {
  it("are never selectable", () => {
    expect(COMING_SOON_BOX_KEYS).toHaveLength(6);
    for (const key of COMING_SOON_BOX_KEYS) {
      expect(isBoxKey(key)).toBe(false);
      expect(BOX_KEYS).not.toContain(key);
      expect(Object.keys(BOX_META)).not.toContain(key);
      expect(addBox([], key)).toEqual([]);
    }
  });

  it("are not kept by resolveBoxes even when a saved layout names them", () => {
    const boxes = ["expenses_today", "hot_waiting"] as unknown as HomeBoxKey[];
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
    expect(listIsOn({ lists: { waiting: false, low_stock: true } }, "waiting")).toBe(false);
    expect(listIsOn({ lists: { waiting: false, low_stock: true } }, "low_stock")).toBe(true);
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
