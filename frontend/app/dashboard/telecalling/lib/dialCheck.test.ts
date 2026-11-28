import { describe, expect, it } from "vitest";
import { callingFromLabel, checkKey, stateTone, worthChecking } from "./dialCheck";

describe("dial check helpers", () => {
  it("maps a check state to a tone", () => {
    expect(stateTone("ok")).toBe("ok");
    expect(stateTone("blocked")).toBe("bad");
    expect(stateTone("warn")).toBe("warn");
    expect(stateTone("not_checked")).toBe("muted");
  });
  it("names where the call comes from", () => {
    expect(callingFromLabel("sim")).toBe("Your phone (SIM)");
    expect(callingFromLabel("office")).toBe("Office number");
  });
  it("only checks when there are 10 digits and no letters", () => {
    expect(worthChecking("98431 2")).toBe(false);
    expect(worthChecking("98431 20123")).toBe(true);
    expect(worthChecking("98431 20123 abc")).toBe(false);
  });
  it("gives a new cache key when the caller or call round changes", () => {
    expect(checkKey("9843120123", "a", 0)).not.toBe(checkKey("9843120123", "b", 0));
    expect(checkKey("9843120123", "a", 0)).not.toBe(checkKey("9843120123", "a", 1));
    expect(checkKey("9843120123", null, 0)).toBe(checkKey("9843120123", undefined, 0));
  });
});
