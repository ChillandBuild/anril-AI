import { describe, expect, it } from "vitest";
import {
  GSTIN_PATTERN,
  asksForGstin,
  finishSetupCard,
  gstTypeFor,
  LOGIN_PAUSE_MS,
  NO_TRIES,
  addWrongTry,
  checkNewPassword,
  errorCode,
  formatCountdown,
  isWrongPasswordError,
  mustChangePassword,
  parseTries,
  pauseSecondsLeft,
  connectLinkFor,
  whatsAppUseFromQuery,
  homeSetupCardKind,
} from "./helpers";

describe("login pause", () => {
  it("pauses on the 5th wrong password for 10 minutes, not before", () => {
    let t = NO_TRIES;
    for (let i = 0; i < 4; i++) {
      t = addWrongTry(t, 1000 + i);
      expect(pauseSecondsLeft(t, 1004)).toBe(0);
    }
    t = addWrongTry(t, 2000);
    expect(t.pausedUntil).toBe(2000 + LOGIN_PAUSE_MS);
    expect(pauseSecondsLeft(t, 2000)).toBe(600);
    expect(pauseSecondsLeft(t, 2000 + LOGIN_PAUSE_MS)).toBe(0);
  });

  it("forgets old wrong tries after an hour", () => {
    let t = NO_TRIES;
    for (let i = 0; i < 4; i++) t = addWrongTry(t, 1000);
    t = addWrongTry(t, 1000 + 2 * 60 * 60 * 1000);
    expect(t.count).toBe(1);
    expect(t.pausedUntil).toBe(0);
  });

  it("reads bad storage as no tries", () => {
    expect(parseTries(null)).toEqual(NO_TRIES);
    expect(parseTries("{oops")).toEqual(NO_TRIES);
    expect(parseTries('{"count":"x","pausedUntil":-5}')).toEqual(NO_TRIES);
    expect(parseTries('{"count":2,"lastAt":5,"pausedUntil":9}')).toEqual({ count: 2, lastAt: 5, pausedUntil: 9 });
  });

  it("counts only a wrong password, not a network failure", () => {
    expect(isWrongPasswordError({ code: "invalid_credentials" })).toBe(true);
    expect(isWrongPasswordError({ message: "Invalid login credentials" })).toBe(true);
    expect(isWrongPasswordError({ message: "Failed to fetch" })).toBe(false);
    expect(isWrongPasswordError(null)).toBe(false);
  });

  it("formats the countdown as m:ss", () => {
    expect(formatCountdown(600)).toBe("10:00");
    expect(formatCountdown(65)).toBe("1:05");
    expect(formatCountdown(-3)).toBe("0:00");
  });
});

describe("first-login password", () => {
  it("is asked only when the flag is exactly true", () => {
    expect(mustChangePassword({ user_metadata: { must_change_password: true } })).toBe(true);
    expect(mustChangePassword({ user_metadata: { must_change_password: false } })).toBe(false);
    expect(mustChangePassword({ user_metadata: { must_change_password: "true" } })).toBe(false);
    expect(mustChangePassword({ user_metadata: null })).toBe(false);
    expect(mustChangePassword(null)).toBe(false);
  });

  it("checks the new password", () => {
    expect(checkNewPassword({ current: "", next: "abcdefgh", again: "abcdefgh" })).toMatch(/given/);
    expect(checkNewPassword({ current: "old", next: "short", again: "short" })).toMatch(/at least 8/);
    expect(checkNewPassword({ current: "samesame1", next: "samesame1", again: "samesame1" })).toMatch(/different/);
    expect(checkNewPassword({ current: "old-pass-1", next: "new-pass-22", again: "new-pass-23" })).toMatch(/match/);
    expect(checkNewPassword({ current: "old-pass-1", next: "new-pass-22", again: "new-pass-22" })).toBeNull();
  });
});

describe("errorCode", () => {
  it("keeps a short readable code, never a long digest", () => {
    expect(errorCode("1234567890abcdef")).toBe("1234567890");
    expect(errorCode("a-b_c")).toBe("abc");
    expect(errorCode(undefined)).toBeNull();
    expect(errorCode("  ")).toBeNull();
  });
});

describe("GSTIN_PATTERN", () => {
  it("accepts a real-looking GSTIN and rejects typos", () => {
    expect(GSTIN_PATTERN.test("33ABCDE1234F1Z5")).toBe(true);
    expect(GSTIN_PATTERN.test("33abcde1234f1z5")).toBe(false);
    expect(GSTIN_PATTERN.test("33ABCDE1234F1Z")).toBe(false);
    expect(GSTIN_PATTERN.test("")).toBe(false);
  });
});

describe("GST choice", () => {
  it("maps each pick to the bill type", () => {
    expect(gstTypeFor("yes")).toBe("regular");
    expect(gstTypeFor("composition")).toBe("composition");
    expect(gstTypeFor("no")).toBe("none");
  });
  it("asks for a GSTIN only when registered", () => {
    expect(asksForGstin("yes")).toBe(true);
    expect(asksForGstin("composition")).toBe(true);
    expect(asksForGstin("no")).toBe(false);
    expect(asksForGstin(null)).toBe(false);
  });
});

describe("finishSetupCard", () => {
  it("counts the steps done and names the card", () => {
    expect(finishSetupCard(["business", "items", "hours"])).toEqual({ done: 3, total: 6, finished: false, title: "Finish setup (3 of 6 done)" });
  });
  it("ignores repeats and unknown steps, and finishes at 6", () => {
    expect(finishSetupCard(["business", "business", "nope"]).done).toBe(1);
    expect(finishSetupCard(["business", "items", "hours", "alerts", "connect", "ai"]).finished).toBe(true);
    expect(finishSetupCard(null).done).toBe(0);
  });
});

describe("setup step 5: how to use WhatsApp", () => {
  it("round-trips the choice through the Connect accounts link", () => {
    expect(connectLinkFor("keep_phone")).toBe("/dashboard/settings/connect-channels?how=keep-phone");
    expect(whatsAppUseFromQuery("keep-phone")).toBe("keep_phone");
    expect(whatsAppUseFromQuery(new URL("http://x" + connectLinkFor("anril_only")).searchParams.get("how"))).toBe("anril_only");
    expect(whatsAppUseFromQuery("other")).toBeNull();
    expect(whatsAppUseFromQuery(null)).toBeNull();
  });
});

describe("Home setup card", () => {
  it("says 'connect your accounts' once the owner moved past step 5 without connecting", () => {
    expect(homeSetupCardKind(["business", "items", "hours", "alerts", "ai"], "ai")).toBe("connect");
    expect(homeSetupCardKind(["business"], "ai")).toBe("connect");
    expect(homeSetupCardKind(["business", "items", "hours", "alerts", "ai"], "business")).toBe("connect");
  });
  it("shows the usual progress card before step 5, and nothing when all 6 are done", () => {
    expect(homeSetupCardKind(["business"], "items")).toBe("progress");
    expect(homeSetupCardKind([], null)).toBe("progress");
    expect(homeSetupCardKind(["business", "items", "hours", "alerts", "connect"], "ai")).toBe("progress");
    expect(homeSetupCardKind(["business", "items", "hours", "alerts", "connect", "ai"], "ai")).toBe("none");
  });
});
