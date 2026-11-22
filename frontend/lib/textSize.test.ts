import { describe, expect, it } from "vitest";
import {
  DARKER_TEXT_KEY,
  TEXT_SIZE_INIT_SCRIPT,
  TEXT_SIZE_KEY,
  applyTextSettings,
  parseDarkerText,
  parseTextSize,
  readDarkerText,
  readTextSize,
  saveDarkerText,
  saveTextSize,
} from "./textSize";

const store = (initial: Record<string, string> = {}) => {
  const data = { ...initial };
  return { data, getItem: (k: string) => data[k] ?? null, setItem: (k: string, v: string) => void (data[k] = v) };
};
const throwing = {
  getItem: () => {
    throw new Error("blocked");
  },
  setItem: () => {
    throw new Error("blocked");
  },
};
const root = () => {
  const attrs: Record<string, string> = {};
  return { attrs, setAttribute: (k: string, v: string) => void (attrs[k] = v) };
};

describe("parse", () => {
  it("keeps the three sizes and turns anything else into normal", () => {
    expect(parseTextSize("normal")).toBe("normal");
    expect(parseTextSize("big")).toBe("big");
    expect(parseTextSize("bigger")).toBe("bigger");
    for (const bad of [null, undefined, "", "huge", "BIG", 3, {}]) expect(parseTextSize(bad)).toBe("normal");
  });

  it("darker text is on only for exactly 1", () => {
    expect(parseDarkerText("1")).toBe(true);
    for (const other of ["0", "", "true", null, undefined, 1]) expect(parseDarkerText(other)).toBe(false);
  });
});

describe("read", () => {
  it("reads what was saved", () => {
    const s = store({ [TEXT_SIZE_KEY]: "bigger", [DARKER_TEXT_KEY]: "1" });
    expect(readTextSize(s)).toBe("bigger");
    expect(readDarkerText(s)).toBe(true);
  });

  it("a bad value or empty storage reads as normal / off", () => {
    expect(readTextSize(store({ [TEXT_SIZE_KEY]: "gigantic" }))).toBe("normal");
    expect(readTextSize(store())).toBe("normal");
    expect(readDarkerText(store())).toBe(false);
    expect(readTextSize(null)).toBe("normal");
  });

  it("storage that throws reads as normal / off", () => {
    expect(readTextSize(throwing)).toBe("normal");
    expect(readDarkerText(throwing)).toBe(false);
  });
});

describe("apply and save", () => {
  it("sets both attributes on <html>", () => {
    const r = root();
    applyTextSettings("big", true, r);
    expect(r.attrs).toEqual({ "data-text-size": "big", "data-darker-text": "1" });
    applyTextSettings("normal", false, r);
    expect(r.attrs).toEqual({ "data-text-size": "normal", "data-darker-text": "0" });
  });

  it("does nothing with no <html> (server)", () => {
    expect(() => applyTextSettings("big", true, null)).not.toThrow();
  });

  it("saving writes the key; saving never throws when storage is blocked", () => {
    const s = store();
    saveTextSize("big", s);
    saveDarkerText(true, s);
    expect(s.data).toEqual({ [TEXT_SIZE_KEY]: "big", [DARKER_TEXT_KEY]: "1" });
    expect(() => saveTextSize("bigger", throwing)).not.toThrow();
    expect(() => saveDarkerText(false, throwing)).not.toThrow();
  });
});

describe("the before-first-paint script", () => {
  const run = (storage: unknown) => {
    const r = root();
    new Function("localStorage", "document", TEXT_SIZE_INIT_SCRIPT)(storage, { documentElement: r });
    return r.attrs;
  };

  it("applies the saved choice", () => {
    expect(run(store({ [TEXT_SIZE_KEY]: "big", [DARKER_TEXT_KEY]: "1" }))).toEqual({ "data-text-size": "big", "data-darker-text": "1" });
  });

  it("defaults to normal for nothing saved, a bad value, or storage that throws", () => {
    const normal = { "data-text-size": "normal", "data-darker-text": "0" };
    expect(run(store())).toEqual(normal);
    expect(run(store({ [TEXT_SIZE_KEY]: "huge", [DARKER_TEXT_KEY]: "yes" }))).toEqual(normal);
    expect(run(throwing)).toEqual(normal);
  });
});
