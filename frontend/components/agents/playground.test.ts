import { describe, expect, it } from "vitest";
import { formatMs, formatToolCall, parseToolOutput, replySourceLine, scoreLabel, sourceText, toolNameError } from "./playground";

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
  it("shows the judge's 0 to 3 mark plainly, clamped", () => {
    expect(scoreLabel(3)).toBe("Match 3 of 3");
    expect(scoreLabel(0)).toBe("Match 0 of 3");
    expect(scoreLabel(5)).toBe("Match 3 of 3");
    expect(scoreLabel(-1)).toBe("Match 0 of 3");
    expect(scoreLabel(null)).toBe("");
  });
});

describe("sourceText", () => {
  it("gives the title and the page or page range", () => {
    expect(sourceText({ document: "Book 7", page_from: 212, page_to: 213 })).toBe("Book 7, pp. 212-213");
    expect(sourceText({ document: "Main resource", page_from: 12, page_to: 12 })).toBe("Main resource, p. 12");
  });
});

describe("replySourceLine", () => {
  const sources = [
    { document: "Main resource", page_from: 12, page_to: 12 },
    { document: "Book 7", page_from: 212, page_to: 213 },
  ];
  it("lists the sources for a book answer", () => {
    expect(replySourceLine("primary", sources)).toBe("From Main resource, p. 12; Book 7, pp. 212-213");
    expect(replySourceLine("book", [sources[1]])).toBe("From Book 7, pp. 212-213");
  });
  it("says an own answer is not from the books", () => {
    expect(replySourceLine("own", [])).toBe("Own reading, not from the books");
  });
  it("shows nothing for chat, null, missing, or a book answer with no sources", () => {
    expect(replySourceLine("chat", sources)).toBe("");
    expect(replySourceLine(null, sources)).toBe("");
    expect(replySourceLine(undefined, undefined)).toBe("");
    expect(replySourceLine("book", [])).toBe("");
  });
});
