import { describe, expect, it } from "vitest";
import { armedAfterFoldChange, pageAtRail } from "./useSidebarRail";

describe("sidebar fold", () => {
  it("keeps hover working after an auto-fold away from the sidebar", () => {
    // Bug: every fold disarmed hover, so the first hover after the 3s
    // auto-fold did nothing until the pointer left and came back.
    expect(armedAfterFoldChange(false)).toBe(true);
  });

  it("still disarms hover when the sidebar folds under the pointer", () => {
    expect(armedAfterFoldChange(true)).toBe(false);
  });

  it("pushes the page while peeking instead of overlaying it", () => {
    // Bug: the peek widened the sidebar but left the page at 64px, under it.
    expect(pageAtRail(true, true)).toBe(false);
    expect(pageAtRail(true, false)).toBe(true);
    expect(pageAtRail(false, false)).toBe(false);
  });
});
