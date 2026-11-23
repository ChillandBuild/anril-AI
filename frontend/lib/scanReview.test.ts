import { describe, expect, it } from "vitest";
import { checkRow, nameMissing, parseScanCsv, phoneLooksWrong, rowsToCsv } from "./scanReview";

describe("scan review (v9.2 #116)", () => {
  it("reads the scan CSV, quoted cells included", () => {
    expect(parseScanCsv('name,phone\n"Ravi, K",98400 12345\n???,9840012346\n')).toEqual([
      { name: "Ravi, K", phone: "98400 12345" },
      { name: "???", phone: "9840012346" },
    ]);
    expect(parseScanCsv("phone\n9840012345")).toEqual([{ name: "", phone: "9840012345" }]);
    expect(parseScanCsv("foo,bar\n1,2")).toEqual([]);
  });

  it("flags numbers that are not Indian mobiles", () => {
    for (const ok of ["9840012345", "+91 98400 12345", "919840012345", "09840012345", "98400-12345"]) {
      expect(phoneLooksWrong(ok)).toBe(false);
    }
    for (const bad of ["984001234", "1234567890", "98400123456", "98400l2345", ""]) {
      expect(phoneLooksWrong(bad)).toBe(true);
    }
  });

  it("flags names the reader couldn't make out", () => {
    expect(nameMissing("")).toBe(true);
    expect(nameMissing("R?vi")).toBe(true);
    expect(nameMissing("[unclear]")).toBe(true);
    expect(nameMissing("Revathi")).toBe(false);
    expect(checkRow({ name: "", phone: "123" })).toEqual({ nameMissing: true, phoneWrong: true });
  });

  it("writes CSV back with blank names instead of question marks", () => {
    expect(rowsToCsv([{ name: "???", phone: "9840012345" }, { name: 'A "B"', phone: "9840012346" }]))
      .toBe('name,phone\n,9840012345\n"A ""B""",9840012346');
    expect(rowsToCsv([{ name: "=HYPERLINK(1)", phone: "+91 98400 12345" }])).toBe("name,phone\n'=HYPERLINK(1),+91 98400 12345");
  });
});
