import { describe, expect, it } from "vitest";
import { MAX_INTERESTED_ITEMS, toggleItem } from "./interestedIn";

describe("toggleItem", () => {
  it("adds an item at the end", () => {
    expect(toggleItem(["a"], "b")).toEqual(["a", "b"]);
  });
  it("removes an item that is already picked", () => {
    expect(toggleItem(["a", "b"], "a")).toEqual(["b"]);
  });
  it("stops at the cap", () => {
    const full = Array.from({ length: MAX_INTERESTED_ITEMS }, (_, i) => String(i));
    expect(toggleItem(full, "new")).toEqual(full);
    expect(toggleItem(full, "3")).toHaveLength(MAX_INTERESTED_ITEMS - 1);
  });
});
