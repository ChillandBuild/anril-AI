import { describe, expect, it } from "vitest";
import { setupSteps } from "./overviewSteps";

const base = {
  characters: 1, live_characters: 1, people: 0, messages_this_week: 0, active_keys: 1,
  key_last_used_at: null, model: "gemini-3.1-flash", model_ready: true,
};

describe("setupSteps", () => {
  it("ticks live and key, leaves seen open until the first site call", () => {
    expect(setupSteps(base).map((s) => s.done)).toEqual([true, true, false]);
    expect(setupSteps({ ...base, key_last_used_at: "2026-11-09T10:00:00Z" }).map((s) => s.done)).toEqual([true, true, true]);
  });

  it("a brand-new business starts with nothing done", () => {
    const steps = setupSteps({ ...base, characters: 0, live_characters: 0, active_keys: 0 });
    expect(steps.map((s) => s.done)).toEqual([false, false, false]);
    expect(steps[0].action).toBe("Create a character");
  });
});
