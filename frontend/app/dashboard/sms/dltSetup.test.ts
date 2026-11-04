import { describe, expect, it } from "vitest";
import { isValidSenderId, matchesQuery, parseSenderIds, parseDltSub, setupSubFor } from "./dltSetup";

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

describe("parseDltSub", () => {
  it("follows ?sub= and defaults to entities", () => {
    expect(parseDltSub("senders")).toBe("senders");
    expect(parseDltSub("templates")).toBe("templates");
    expect(parseDltSub("entities")).toBe("entities");
    expect(parseDltSub("nope")).toBe("entities");
    expect(parseDltSub(null)).toBe("entities");
  });
});

describe("setupSubFor (old deep links still land sensibly)", () => {
  it("opens Entity ID for the old entity and PE-TM tabs and for no params", () => {
    expect(setupSubFor("entity", null)).toBe("entities");
    expect(setupSubFor("petm", null)).toBe("entities");
    expect(setupSubFor("petm", "senders")).toBe("entities");
    expect(setupSubFor(null, null)).toBe("entities");
  });
  it("follows ?sub= for the manager tab and for a bare ?sub=", () => {
    expect(setupSubFor("manager", "senders")).toBe("senders");
    expect(setupSubFor("manager", "templates")).toBe("templates");
    expect(setupSubFor("manager", null)).toBe("entities");
    expect(setupSubFor(null, "templates")).toBe("templates");
    expect(setupSubFor("nope", "nope")).toBe("entities");
  });
});
