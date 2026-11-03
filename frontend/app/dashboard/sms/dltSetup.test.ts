import { describe, expect, it } from "vitest";
import { isPeTmProof, isValidSenderId, matchesQuery, parseSenderIds, parseDltSub, parseSetupTab, peTmDate, peTmState } from "./dltSetup";

describe("parseSetupTab", () => {
  it("accepts the three tabs and defaults to entity", () => {
    expect(parseSetupTab("manager")).toBe("manager");
    expect(parseSetupTab("petm")).toBe("petm");
    expect(parseSetupTab("entity")).toBe("entity");
    expect(parseSetupTab("nope")).toBe("entity");
    expect(parseSetupTab(null)).toBe("entity");
  });
});

describe("parseSenderIds", () => {
  it("splits on commas and spaces, upper-cases and removes repeats", () => {
    expect(parseSenderIds("anrilx, ANRILX  anrily;\nanrilz")).toEqual(["ANRILX", "ANRILY", "ANRILZ"]);
    expect(parseSenderIds("  ,, ")).toEqual([]);
  });
});

describe("isValidSenderId", () => {
  it("wants 3 to 6 letters", () => {
    expect(isValidSenderId("ANRILX")).toBe(true);
    expect(isValidSenderId("AB")).toBe(false);
    expect(isValidSenderId("ANRILXY")).toBe(false);
    expect(isValidSenderId("AN12")).toBe(false);
  });
});

describe("matchesQuery", () => {
  it("matches any field, ignoring case", () => {
    expect(matchesQuery(["Ravi Stores", null], "ravi")).toBe(true);
    expect(matchesQuery([null, "1101234567890"], "0123")).toBe(true);
    expect(matchesQuery(["abc"], "xyz")).toBe(false);
    expect(matchesQuery(["abc"], "  ")).toBe(true);
  });
});

describe("isPeTmProof", () => {
  it("accepts jpg, jpeg, png, pdf only", () => {
    expect(isPeTmProof("binding.PNG")).toBe(true);
    expect(isPeTmProof("a.b.jpeg")).toBe(true);
    expect(isPeTmProof("scan.pdf")).toBe(true);
    expect(isPeTmProof("doc.docx")).toBe(false);
    expect(isPeTmProof("pdf")).toBe(false);
  });
});

describe("peTmState", () => {
  it("lets the client confirm only after TM approval and only once", () => {
    expect(peTmState({ tm_approved_at: null, pe_confirmed_at: null }).canConfirm).toBe(false);
    expect(peTmState({ tm_approved_at: "2026-11-03T10:00:00Z", pe_confirmed_at: null }).canConfirm).toBe(true);
    expect(peTmState({ tm_approved_at: "2026-11-03T10:00:00Z", pe_confirmed_at: "2026-11-03T11:00:00Z" })).toEqual({ tmApproved: true, done: true, canConfirm: false });
  });
});

describe("peTmDate", () => {
  it("prefers the latest step reached", () => {
    expect(peTmDate({ tm_approved_at: null, pe_confirmed_at: null, created_at: "c" })).toBe("c");
    expect(peTmDate({ tm_approved_at: "t", pe_confirmed_at: null, created_at: "c" })).toBe("t");
    expect(peTmDate({ tm_approved_at: "t", pe_confirmed_at: "p", created_at: "c" })).toBe("p");
  });
});

describe("parseDltSub", () => {
  it("follows ?sub= and defaults to entities", () => {
    expect(parseDltSub("senders")).toBe("senders");
    expect(parseDltSub("templates")).toBe("templates");
    expect(parseDltSub("entities")).toBe("entities");
    expect(parseDltSub("nope")).toBe("entities");
    expect(parseDltSub(null)).toBe("entities");
  });
});
