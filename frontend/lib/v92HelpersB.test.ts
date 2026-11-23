import { afterEach, describe, expect, it, vi } from "vitest";
import { afterHoursProblem, MEDIA_RULE_PRESETS } from "./replySettingsApi";
import { tidyWebsite, undoQuestion } from "./knowledgeWebApi";
import { canReconnect, disconnectedMessage, reportClientError } from "./connectionStatusApi";

describe("afterHoursProblem", () => {
  const ok = { enabled: true, open: "09:00", close: "21:00", message: "Back at 9." };
  it("accepts a complete setting", () => expect(afterHoursProblem(ok)).toBeNull());
  it("accepts off with no message", () => expect(afterHoursProblem({ ...ok, enabled: false, message: "" })).toBeNull());
  it("asks for the message before switching on", () => expect(afterHoursProblem({ ...ok, message: "  " })).toMatch(/Write the message/));
  it("refuses a bad time", () => expect(afterHoursProblem({ ...ok, open: "9am" })).toMatch(/hours and minutes/));
  it("refuses a message over the limit", () => expect(afterHoursProblem({ ...ok, message: "x".repeat(301) })).toMatch(/under 300/));
});

describe("media rule presets", () => {
  it("each preset fits the 300 character limit", () => {
    for (const p of MEDIA_RULE_PRESETS) expect(p.text.length).toBeLessThanOrEqual(300);
  });
});

describe("website and undo helpers", () => {
  it("adds https when missing and trims", () => {
    expect(tidyWebsite("  shop.example/about ")).toBe("https://shop.example/about");
    expect(tidyWebsite("http://shop.example")).toBe("http://shop.example");
    expect(tidyWebsite("   ")).toBe("");
  });
  it("words the undo question for the Description and for a file", () => {
    expect(undoQuestion({ available: true, version_id: "v1", kind: "description", label: "Description", changed_at: "x" })).toMatch(/business Description/);
    expect(undoQuestion({ available: true, version_id: "v2", kind: "facts", label: "prices.pdf", changed_at: "x" })).toMatch(/prices\.pdf/);
    expect(undoQuestion({ available: false })).toBe("");
  });
});

describe("connection banner helpers", () => {
  it("names a single number and hides the phone number", () => {
    expect(disconnectedMessage({ disconnected: true, numbers: [{ id: "1", name: "Main shop" }] })).toMatch(/^Main shop is disconnected/);
  });
  it("speaks generally for several numbers and says nothing when fine", () => {
    expect(disconnectedMessage({ disconnected: true, numbers: [{ id: "1", name: "A" }, { id: "2", name: "B" }] })).toMatch(/Some of your WhatsApp numbers/);
    expect(disconnectedMessage({ disconnected: false, numbers: [] })).toBe("");
  });
  it("shows the banner to the owner or settings.manage only", () => {
    expect(canReconnect("owner", [])).toBe(true);
    expect(canReconnect("manager", ["settings.manage"])).toBe(true);
    expect(canReconnect("agent", ["leads.view"])).toBe(false);
    expect(canReconnect(null, undefined)).toBe(false);
  });
});

describe("reportClientError", () => {
  afterEach(() => vi.unstubAllGlobals());
  function fakeStorage() {
    const data = new Map<string, string>();
    return { getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => void data.set(k, v) };
  }
  it("marks the session before sending, so a second error is not sent", () => {
    const store = fakeStorage();
    vi.stubGlobal("sessionStorage", store);
    reportClientError("abc", "/dashboard");
    expect(store.getItem("anril_error_reported")).toBe("1");
    reportClientError("def", "/dashboard"); // returns early, never throws
  });
  it("never throws when storage is blocked", () => {
    vi.stubGlobal("sessionStorage", { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } });
    expect(() => reportClientError("abc", "/x")).not.toThrow();
  });
});
