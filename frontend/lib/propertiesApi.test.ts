import { describe, expect, it } from "vitest";
import { formatPriceWords, kindLine, parseMoneyInput, parseWholeNumber, priceRangeText, unitsText } from "./propertiesApi";

describe("formatPriceWords", () => {
  it("uses lakh and crore", () => {
    expect(formatPriceWords(450_000_000)).toBe("₹45 lakh");
    expect(formatPriceWords(125_000_000)).toBe("₹12.5 lakh");
    expect(formatPriceWords(12_000_000_000)).toBe("₹12 crore");
    expect(formatPriceWords(1_250_000_000)).toBe("₹1.25 crore");
  });
  it("shows small amounts in rupees and nothing for null", () => {
    expect(formatPriceWords(8_500_000)).toBe("₹85,000");
    expect(formatPriceWords(null)).toBe("");
  });
});

describe("priceRangeText", () => {
  it("joins a range, collapses an equal one, handles one end", () => {
    expect(priceRangeText(450_000_000, 600_000_000)).toBe("₹45 lakh to ₹60 lakh");
    expect(priceRangeText(450_000_000, 450_000_000)).toBe("₹45 lakh");
    expect(priceRangeText(null, 600_000_000)).toBe("₹60 lakh");
    expect(priceRangeText(undefined, undefined)).toBe("");
  });
});

describe("parseMoneyInput", () => {
  it("reads plain rupees, lakh and crore words", () => {
    expect(parseMoneyInput("4500000")).toBe(450_000_000);
    expect(parseMoneyInput("45,00,000")).toBe(450_000_000);
    expect(parseMoneyInput("₹45 lakh")).toBe(450_000_000);
    expect(parseMoneyInput("45L")).toBe(450_000_000);
    expect(parseMoneyInput("1.2 cr")).toBe(1_200_000_000);
    expect(parseMoneyInput("1.2 crore")).toBe(1_200_000_000);
  });
  it("empty is null and nonsense is undefined", () => {
    expect(parseMoneyInput("  ")).toBeNull();
    expect(parseMoneyInput("lots")).toBeUndefined();
    expect(parseMoneyInput("-5")).toBeUndefined();
  });
});

describe("parseWholeNumber", () => {
  it("accepts digits only", () => {
    expect(parseWholeNumber("20")).toBe(20);
    expect(parseWholeNumber("")).toBeNull();
    expect(parseWholeNumber("2.5")).toBeUndefined();
    expect(parseWholeNumber("x")).toBeUndefined();
  });
});

describe("kindLine and unitsText", () => {
  it("describes the property", () => {
    expect(kindLine({ kind: "flat", bhk: 3 })).toBe("3 BHK flat");
    expect(kindLine({ kind: "plot", bhk: null })).toBe("Plot");
  });
  it("describes the units", () => {
    expect(unitsText(12, 20)).toBe("12 of 20 left");
    expect(unitsText(5, null)).toBe("5 left");
    expect(unitsText(0, 20)).toBe("Sold out");
    expect(unitsText(null, null)).toBe("Not counted");
  });
});
