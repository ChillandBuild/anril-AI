import { describe, expect, it } from "vitest";
import {
  GSTIN_PATTERN,
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
