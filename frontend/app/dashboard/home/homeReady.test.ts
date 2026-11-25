import { describe, expect, it } from "vitest";
import { HOME_WAIT_CAP_MS, homeIsReady, type HomeParts } from "./homeReady";

const ALL: HomeParts = { today: true, layout: true, setup: true, adSpend: true, teamCalls: true };
const NONE: HomeParts = { today: false, layout: false, setup: false, adSpend: false, teamCalls: false };

// The bug: Home opened as soon as the shell was up and then filled in piece by piece.
describe("homeIsReady", () => {
  it("opens at once when every call has finished", () => {
    expect(homeIsReady(ALL, 0)).toBe(true);
  });

  it("stays closed while nothing has come back yet", () => {
    expect(homeIsReady(NONE, 0)).toBe(false);
    expect(homeIsReady(NONE, HOME_WAIT_CAP_MS - 1)).toBe(false);
    expect(homeIsReady({ ...ALL, adSpend: false }, HOME_WAIT_CAP_MS - 1)).toBe(false);
  });

  it("stays closed while a top-of-page call is still out, even if the rest are in", () => {
    expect(homeIsReady({ ...ALL, today: false }, 1_000)).toBe(false);
    expect(homeIsReady({ ...ALL, layout: false }, 1_000)).toBe(false);
    expect(homeIsReady({ ...ALL, setup: false }, 1_000)).toBe(false);
  });

  it("waits for the chart cards at the bottom too, so nothing pops in after the page opens", () => {
    expect(homeIsReady({ ...ALL, adSpend: false }, 1_000)).toBe(false);
    expect(homeIsReady({ ...ALL, teamCalls: false }, 1_000)).toBe(false);
  });

  it("opens anyway once the wait cap has passed, so a stuck call cannot trap the person on the loader", () => {
    expect(homeIsReady(NONE, HOME_WAIT_CAP_MS)).toBe(true);
    expect(homeIsReady({ ...ALL, today: false }, HOME_WAIT_CAP_MS + 1)).toBe(true);
  });
});
