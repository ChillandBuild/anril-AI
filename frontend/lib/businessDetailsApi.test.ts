import { describe, expect, it } from "vitest";
import { EMPTY_BUSINESS_DETAILS, imageProblem, withDefaults } from "./businessDetailsApi";

describe("withDefaults", () => {
  it("fills the fields an older backend leaves out", () => {
    const d = withDefaults({ legal_name: "Shree Silks", prices_include_gst: false });
    expect(d.legal_name).toBe("Shree Silks");
    expect(d.prices_include_gst).toBe(false);
    expect(d.gst_type).toBe("regular");
    expect(d.bill_prefix).toBe("");
  });
  it("copes with nothing", () => {
    expect(withDefaults(null)).toEqual(EMPTY_BUSINESS_DETAILS);
  });
});

describe("imageProblem", () => {
  it("accepts png, jpg and webp up to 1 MB", () => {
    for (const type of ["image/png", "image/jpeg", "image/webp"]) {
      expect(imageProblem({ type, size: 1024 * 1024 })).toBeNull();
    }
  });
  it("refuses other types and big files in plain words", () => {
    expect(imageProblem({ type: "image/gif", size: 10 })).toMatch(/PNG, JPG or WEBP/);
    expect(imageProblem({ type: "image/png", size: 1024 * 1024 + 1 })).toMatch(/under 1 MB/);
  });
});
