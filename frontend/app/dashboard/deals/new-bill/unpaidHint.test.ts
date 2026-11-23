import { describe, expect, it } from "vitest";
import { unpaidHintText } from "./unpaidHint";

describe("New bill unpaid hint", () => {
  it("says 1 unpaid order, then 2 unpaid orders", () => {
    expect(unpaidHintText(1)).toBe("1 unpaid order");
    expect(unpaidHintText(2)).toBe("2 unpaid orders");
  });
});
