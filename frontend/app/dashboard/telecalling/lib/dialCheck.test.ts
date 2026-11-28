import { describe, expect, it } from "vitest";
import { callingFromLabel, checkKey, defaultDialMode, initialsOf, lastChatWords, stateTone, worthChecking } from "./dialCheck";

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
  it("picks the default Office / SIM choice from the check, else the business setting", () => {
    expect(defaultDialMode("sim", "telecmi")).toBe("sim");
    expect(defaultDialMode("office", "sim_basic")).toBe("office");
    expect(defaultDialMode(undefined, "sim_basic")).toBe("sim");
    expect(defaultDialMode(undefined, "telecmi")).toBe("office");
    expect(defaultDialMode(null, "telecmi")).toBe("office");
  });
  it("makes two-letter initials, or # when there is no name", () => {
    expect(initialsOf("Asha Raman")).toBe("AR");
    expect(initialsOf("  asha ")).toBe("A");
    expect(initialsOf("Asha Kumari Raman")).toBe("AR");
    expect(initialsOf(null)).toBe("#");
    expect(initialsOf("")).toBe("#");
  });
  it("says when the last chat was in plain words", () => {
    const now = new Date("2026-11-28T10:00:00+05:30");
    expect(lastChatWords("2026-11-28T08:00:00+05:30", now)).toBe("today");
    expect(lastChatWords("2026-11-27T23:00:00+05:30", now)).toBe("yesterday");
    expect(lastChatWords("2026-11-25T09:00:00+05:30", now)).toBe("3 days ago");
    expect(lastChatWords("2026-10-01T09:00:00+05:30", now)).toBe("58 days ago");
    expect(lastChatWords("nonsense", now)).toBeNull();
    expect(lastChatWords(null, now)).toBeNull();
  });
});
