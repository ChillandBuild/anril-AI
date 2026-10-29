import { describe, expect, it } from "vitest";
import { buildCsv } from "./exportCsv";

describe("buildCsv", () => {
  it("starts with a byte-order mark and uses CRLF rows", () => {
    expect(buildCsv(["A", "B"], [["1", "2"]])).toBe("﻿A,B\r\n1,2");
  });

  it("quotes commas, quotes and line breaks", () => {
    expect(buildCsv(["A"], [['Hi, "Asha"'], ["two\nlines"]])).toBe('﻿A\r\n"Hi, ""Asha"""\r\n"two\nlines"');
  });

  it("keeps phone numbers but defuses formulas", () => {
    const out = buildCsv(["A"], [["+91 98765 43210"], ["=SUM(A1)"], ["@cmd"], ["-5+3"], ["+cmd|x"]]).split("\r\n");
    expect(out.slice(1)).toEqual(["+91 98765 43210", "'=SUM(A1)", "'@cmd", "'-5+3", "'+cmd|x"]);
  });

  it("leaves Tamil text alone", () => {
    expect(buildCsv(["A"], [["வணக்கம்"]])).toContain("வணக்கம்");
  });
});
