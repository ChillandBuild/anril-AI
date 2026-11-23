import { describe, expect, it } from "vitest";
import { fillFromGstin, gstinCheckChar, readGstin } from "./gstin";

describe("readGstin", () => {
  it("reads state and PAN from a real GSTIN and checks the last character", () => {
    const r = readGstin("27aapfu0939f1zv");
    expect(r).toEqual({
      status: "ok", gstin: "27AAPFU0939F1ZV", stateCode: "27", stateName: "Maharashtra", pan: "AAPFU0939F", checkMatches: true,
    });
  });

  it("flags a typo in the last character without refusing it", () => {
    const r = readGstin("27AAPFU0939F1ZX");
    expect(r.status).toBe("ok");
    expect(r.status === "ok" && r.checkMatches).toBe(false);
  });

  it("waits while typing and says what is wrong with a bad one", () => {
    expect(readGstin("")).toEqual({ status: "empty" });
    expect(readGstin("33ABC")).toEqual({ status: "typing" });
    expect(readGstin("33ABCDE1234F1X5").status).toBe("bad");
    expect(readGstin("99ABCDE1234F1Z5").status).toBe("bad");
  });

  it("works out the check character", () => {
    expect(gstinCheckChar("27AAPFU0939F1Z")).toBe("V");
  });
});

describe("fillFromGstin", () => {
  const ok = readGstin("33ABCDE1234F1Z5");

  it("fills state code, PAN and an empty state", () => {
    expect(fillFromGstin(ok, { state: "" })).toEqual({ state_code: "33", pan: "ABCDE1234F", state: "Tamil Nadu" });
  });

  it("replaces another known state but keeps a hand-typed spelling", () => {
    expect(fillFromGstin(ok, { state: "Kerala" })?.state).toBe("Tamil Nadu");
    expect(fillFromGstin(ok, { state: "TN" })).toEqual({ state_code: "33", pan: "ABCDE1234F" });
  });

  it("fills nothing until the GSTIN is complete", () => {
    expect(fillFromGstin(readGstin("33AB"), { state: "" })).toBeNull();
  });
});
