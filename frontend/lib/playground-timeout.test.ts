import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({ auth: { getSession: async () => ({ data: { session: null } }) } }),
}));

import { companionsApi } from "@/lib/api";

// A fetch that never answers on its own: it only ends when the caller's timeout aborts it.
function hangingFetch() {
  return vi.fn((_url: string, init: RequestInit) =>
    new Promise((_resolve, reject) => {
      init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    }),
  );
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

// A Playground reply took 15.0s (book search + judge + reply) and the dashboard gave up at 15s, so the
// saved reply never showed. Playground replies now wait up to 60s; every other send keeps 15s.
describe("Playground reply wait", () => {
  it("is still waiting at 15s and only gives up at 60s", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", hangingFetch());
    let settled = false;
    const reply = companionsApi.testChat("c1", "கல்யாணம் எப்போ நடக்கும்?").finally(() => { settled = true; });
    reply.catch(() => {});

    await vi.advanceTimersByTimeAsync(15_500);
    expect(settled).toBe(false);

    await vi.advanceTimersByTimeAsync(45_000);
    await expect(reply).rejects.toThrow(/timed out/);
  });

  it("leaves other sends at 15s", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", hangingFetch());
    const add = companionsApi.createTestPerson("Prem");
    add.catch(() => {});
    await vi.advanceTimersByTimeAsync(15_500);
    await expect(add).rejects.toThrow(/timed out/);
  });
});
