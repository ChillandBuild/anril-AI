import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { chunkIds, createMarkLoader, mineUrl } from "./replyMarks";

describe("replyMarks", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("chunks ids", () => {
    expect(chunkIds(["a", "b", "c"], 2)).toEqual([["a", "b"], ["c"]]);
    expect(chunkIds([])).toEqual([]);
  });

  it("builds one url for many ids", () => {
    expect(mineUrl(["a", "b"])).toBe("/api/v1/ai-setup/reply-feedback/mine?message_ids=a,b");
  });

  it("asks for everything on screen in one call and hands each reply its own mark", async () => {
    const fetcher = vi.fn(async () => ({ a: { reason: "rude" as const, note: null } }));
    const loader = createMarkLoader(fetcher, 10);
    const pa = loader.get("a");
    const pb = loader.get("b");
    await vi.advanceTimersByTimeAsync(20);
    expect(await pa).toEqual({ reason: "rude", note: null });
    expect(await pb).toBeNull();
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher).toHaveBeenCalledWith(["a", "b"]);
  });

  it("remembers answers and what the person just did", async () => {
    const fetcher = vi.fn(async () => ({}));
    const loader = createMarkLoader(fetcher, 10);
    const first = loader.get("a");
    await vi.advanceTimersByTimeAsync(20);
    await first;
    expect(await loader.get("a")).toBeNull();
    expect(fetcher).toHaveBeenCalledTimes(1);
    loader.set("a", { reason: "wrong", note: "x" });
    expect(await loader.get("a")).toEqual({ reason: "wrong", note: "x" });
  });

  it("answers no mark and tries again later when the call fails", async () => {
    const fetcher = vi.fn().mockRejectedValueOnce(new Error("down")).mockResolvedValueOnce({ a: { reason: "wrong", note: null } });
    const loader = createMarkLoader(fetcher, 10);
    const p1 = loader.get("a");
    await vi.advanceTimersByTimeAsync(20);
    expect(await p1).toBeNull();
    const p2 = loader.get("a");
    await vi.advanceTimersByTimeAsync(20);
    expect(await p2).toEqual({ reason: "wrong", note: null });
  });
});
