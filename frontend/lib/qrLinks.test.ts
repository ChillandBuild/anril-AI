import { describe, expect, it } from "vitest";
import { PRINT_SIZES, defaultFirstMessage, pngFileName, previewScale, printCss, printSize, rupees, statCells, trapTabTarget, validateQrForm } from "./qrLinks";

describe("print sizes", () => {
  it("offers the four sizes in order", () => {
    expect(PRINT_SIZES.map((s) => [s.label, s.paper])).toEqual([
      ["Table card", "A6"], ["Counter stand", "A5"], ["Wall poster", "A4"], ["Sticker", "5 cm"],
    ]);
  });

  it("uses real paper dimensions and a QR that fits with room for text", () => {
    expect(PRINT_SIZES.map((s) => [s.widthMm, s.heightMm])).toEqual([[105, 148], [148, 210], [210, 297], [50, 50]]);
    for (const s of PRINT_SIZES) expect(s.qrMm).toBeLessThan(s.widthMm);
  });

  it("writes an @page rule of exactly the paper size and hides the rest of the page", () => {
    const css = printCss(printSize("wall"));
    expect(css).toContain("@page { size: 210mm 297mm; margin: 0; }");
    expect(css).toContain("body * { visibility: hidden");
    expect(css).toContain(".qr-print-sheet");
    expect(printCss(printSize("sticker"))).toContain("size: 50mm 50mm");
  });
});

describe("print safety", () => {
  it("drops everything but the sheet from the printed page", () => {
    expect(printCss(printSize("table"))).toContain("body > *:not(.qr-print-sheet) { display: none !important; }");
  });

  it("keeps every printed line at 8pt or more, titles at 9pt or more on the sticker", () => {
    for (const s of PRINT_SIZES) expect(Math.min(s.placePt, s.scanPt, s.businessPt)).toBeGreaterThanOrEqual(8);
    const sticker = printSize("sticker");
    expect(Math.min(sticker.placePt, sticker.businessPt)).toBeGreaterThanOrEqual(9);
  });

  it("fits the sticker's three lines and the QR inside 50 mm", () => {
    const s = printSize("sticker");
    const pt = 0.3528; // mm per point
    const text = (s.businessPt + s.scanPt + s.placePt) * pt * 1.2;
    expect(s.qrMm + text + 2 * 2 + 3 * 1).toBeLessThanOrEqual(s.heightMm);
  });
});

describe("preview scale", () => {
  it("shrinks to the box and never grows", () => {
    const a4 = printSize("wall");
    expect(previewScale(294, a4)).toBeCloseTo(294 / (210 * 3.78), 5);
    expect(previewScale(5000, a4)).toBe(1);
    expect(previewScale(0, a4)).toBe(1);
    expect(210 * 3.78 * previewScale(294, a4)).toBeLessThanOrEqual(294);
  });
});

describe("tab trap", () => {
  it("wraps at both ends and pulls stray focus in", () => {
    expect(trapTabTarget(3, 2, false)).toBe(0);
    expect(trapTabTarget(3, 0, true)).toBe(2);
    expect(trapTabTarget(3, 1, false)).toBeNull();
    expect(trapTabTarget(3, -1, false)).toBe(0);
    expect(trapTabTarget(3, -1, true)).toBe(2);
    expect(trapTabTarget(0, -1, false)).toBeNull();
  });
});

describe("form", () => {
  it("prefills the first message from the place name", () => {
    expect(defaultFirstMessage("Table 4")).toBe("Hi, I'm at Table 4");
    expect(defaultFirstMessage("  ")).toBe("Hi");
  });

  it("explains empty and too-long fields", () => {
    expect(validateQrForm({ name: "Table 4", first_message: "Hi" })).toEqual({});
    expect(Object.keys(validateQrForm({ name: " ", first_message: "" }))).toEqual(["name", "first_message"]);
    expect(validateQrForm({ name: "x".repeat(81), first_message: "Hi" }).name).toMatch(/80/);
    expect(validateQrForm({ name: "A", first_message: "x".repeat(301) }).first_message).toMatch(/300/);
  });
});

describe("numbers", () => {
  const base = { opens: 12, chats: 5, new_customers: 3, paid_orders: 2 };

  it("shows the four numbers and hides ₹ when the server did not send it", () => {
    expect(statCells(base).map((c) => c.label)).toEqual(["Scanned", "Chats", "New customers", "Paid"]);
    expect(statCells(base)[3].value).toBe("2");
  });

  it("adds the amount in Indian grouping when it was sent", () => {
    expect(statCells({ ...base, paid_paise: 12345600 })[3].value).toBe("2 (₹1,23,456)");
    expect(rupees(0)).toBe("₹0");
  });
});

describe("png name", () => {
  it("is a safe slug plus the code", () => {
    expect(pngFileName("Table 4 / Patio!", "ABCDE")).toBe("qr-table-4-patio-ABCDE.png");
    expect(pngFileName("???", "ABCDE")).toBe("qr-code-ABCDE.png");
  });
});
