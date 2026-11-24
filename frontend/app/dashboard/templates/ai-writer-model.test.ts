import { describe, expect, it } from "vitest";
import { MAX_PROMPTS, addPrompt } from "./ai-writer-model";

describe("addPrompt", () => {
  it("puts the newest first, drops repeats and keeps the last 5", () => {
    let list: string[] = [];
    for (const p of ["a", "b", "c", "d", "e", "f"]) list = addPrompt(list, p);
    expect(list).toEqual(["f", "e", "d", "c", "b"]);
    expect(addPrompt(list, "c")).toEqual(["c", "f", "e", "d", "b"]);
    expect(addPrompt(list, "   ")).toBe(list);
    expect(list).toHaveLength(MAX_PROMPTS);
  });
});
