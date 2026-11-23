import { describe, expect, it } from "vitest";
import { CHIP_ROW_REM, TAB_BAR_REM, moduleChromeRem, moduleChromeStyle } from "./moduleChrome";

describe("moduleChrome", () => {
  it("adds up only the strips the page has", () => {
    expect(moduleChromeRem({})).toBe(0);
    expect(moduleChromeRem({ tabs: true })).toBe(TAB_BAR_REM);
    expect(moduleChromeRem({ chips: true })).toBe(CHIP_ROW_REM);
    expect(moduleChromeRem({ tabs: true, chips: true })).toBe(5.6);
  });

  it("hands the page a CSS variable it can subtract", () => {
    expect(moduleChromeStyle({ tabs: true, chips: true })).toEqual({ "--module-chrome": "5.6rem" });
    expect(moduleChromeStyle({})).toEqual({ "--module-chrome": "0rem" });
  });
});
