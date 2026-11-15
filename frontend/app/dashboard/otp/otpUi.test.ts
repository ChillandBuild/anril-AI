import { describe, expect, it } from "vitest";
import { percent } from "./otpUi";

describe("percent", () => {
  it("shows null as a dash", () => {
    expect(percent(null)).toBe("—");
  });

  it("rounds to one decimal", () => {
    expect(percent(0.8734)).toBe("87.3%");
  });

  it("drops a trailing .0", () => {
    expect(percent(0.5)).toBe("50%");
    expect(percent(1)).toBe("100%");
    expect(percent(0)).toBe("0%");
  });

  it("keeps a non-zero decimal", () => {
    expect(percent(0.0512)).toBe("5.1%");
  });

  it("treats non-finite numbers as a dash", () => {
    expect(percent(Number.NaN)).toBe("—");
    expect(percent(Number.POSITIVE_INFINITY)).toBe("—");
  });
});
