import { describe, expect, it } from "vitest";
import { formatMs, formatToolCall, parseToolOutput, scoreLabel, toolNameError } from "./playground";

describe("formatToolCall", () => {
  it("shows name and args", () => {
    expect(formatToolCall({ id: "1", name: "get_chart", args: { dob: "1990-04-12" } })).toBe('get_chart({"dob":"1990-04-12"})');
    expect(formatToolCall({ id: "1", name: "get_chart" })).toBe("get_chart()");
  });

  it("cuts long args", () => {
    const out = formatToolCall({ id: "1", name: "t", args: { x: "a".repeat(200) } });
    expect(out.length).toBeLessThanOrEqual(84);
    expect(out.endsWith("…)")).toBe(true);
  });
});

describe("parseToolOutput", () => {
  it("sends a JSON object as an object, anything else as text", () => {
    expect(parseToolOutput(' {"lagna": "Kumbham"} ')).toEqual({ lagna: "Kumbham" });
    expect(parseToolOutput("Lagna is Kumbham")).toBe("Lagna is Kumbham");
    expect(parseToolOutput("{broken")).toBe("{broken");
    expect(parseToolOutput("[1,2]")).toBe("[1,2]");
  });
});

describe("formatMs", () => {
  it("uses ms under a second, seconds above", () => {
    expect(formatMs(820.4)).toBe("820 ms");
    expect(formatMs(1400)).toBe("1.4 s");
  });
});

describe("toolNameError", () => {
  it("matches the backend name rule", () => {
    expect(toolNameError("get_chart", [])).toBe("");
    expect(toolNameError("GetChart", [])).not.toBe("");
    expect(toolNameError("get_chart", ["get_chart"])).toBe("That tool is already in the list.");
  });
});

describe("scoreLabel", () => {
  it("shows similarity as a clamped percent", () => {
    expect(scoreLabel(0.8234)).toBe("82% match");
    expect(scoreLabel(1.2)).toBe("100% match");
    expect(scoreLabel(-0.1)).toBe("0% match");
    expect(scoreLabel(null)).toBe("");
  });
});
