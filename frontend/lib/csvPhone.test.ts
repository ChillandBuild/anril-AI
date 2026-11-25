import { describe, expect, it } from "vitest";
import { isPhoneFormula, phoneCell } from "./csvPhone";
import { toCsv } from "@/components/chats/exportCsv";
import { buildCsv } from "@/app/dashboard/scheduled-templates/exportCsv";

describe("phoneCell", () => {
  it("wraps plain numbers as a text formula", () => {
    expect(phoneCell("+919659950974")).toBe('="+919659950974"');
    expect(phoneCell("  919659950974 ")).toBe('="919659950974"');
    expect(phoneCell("+91 98765 43210")).toBe('="+91 98765 43210"');
    expect(phoneCell(919659950974)).toBe('="919659950974"');
  });
  it("leaves empty values empty", () => {
    expect(phoneCell(null)).toBe("");
    expect(phoneCell(undefined)).toBe("");
    expect(phoneCell("")).toBe("");
    expect(phoneCell("   ")).toBe("");
  });
  it("passes anything that is not a plain number through unchanged", () => {
    expect(phoneCell("=SUM(A1)")).toBe("=SUM(A1)");
    expect(phoneCell("+cmd|x")).toBe("+cmd|x");
    expect(phoneCell("12")).toBe("12");
    expect(phoneCell("abc")).toBe("abc");
  });
});

describe("isPhoneFormula", () => {
  it("recognises only phoneCell output", () => {
    expect(isPhoneFormula(phoneCell("+919659950974"))).toBe(true);
    expect(isPhoneFormula('="1"+HYPERLINK("x")')).toBe(false);
    expect(isPhoneFormula("=SUM(A1)")).toBe(false);
  });
});

describe("phone cells through the CSV writers", () => {
  const expected = '"=""+919659950974"""';
  it("chats toCsv keeps the formula and quotes it", () => {
    const out = toCsv([{ p: "+919659950974", n: "=evil" }], [
      { header: "Phone", value: (r) => phoneCell(r.p) },
      { header: "Name", value: (r) => r.n },
    ]);
    expect(out.split("\r\n")[1]).toBe(`${expected},'=evil`);
  });
  it("scheduled-templates buildCsv keeps the formula and quotes it", () => {
    expect(buildCsv(["Phone"], [[phoneCell("+919659950974")]]).split("\r\n")[1]).toBe(expected);
  });
});
