import { describe, expect, it } from "vitest";
import { featureLabel, formatRupees, maskSupplier } from "./displayLabels";

describe("maskSupplier", () => {
  it("turns the supplier's catalog names into Cloud calling", () => {
    expect(maskSupplier("Telecalling — Tele-CMI")).toBe("Cloud calling");
    expect(maskSupplier("Calling (TeleCMI)")).toBe("Cloud calling");
    expect(maskSupplier("Extra TeleCMI minutes")).toBe("Extra Cloud calling minutes");
  });
});

describe("featureLabel", () => {
  it("never shows a raw feature key", () => {
    expect(featureLabel("ai_speech_to_text", "ai_speech_to_text")).toBe("Voice notes understood");
    expect(featureLabel("ai_text_to_speech")).toBe("AI voice replies");
    expect(featureLabel("some_new_key")).toBe("Some new key");
  });
});

describe("formatRupees", () => {
  it("shows at most two decimals", () => {
    expect(formatRupees(174.125)).toMatch(/^174\.1[23]$/);
    expect(formatRupees(261.625)).toMatch(/^261\.6[23]$/);
    expect(formatRupees(1999)).toBe("1,999");
  });
});
