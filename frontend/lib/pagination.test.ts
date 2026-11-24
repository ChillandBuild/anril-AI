import { describe, expect, it } from "vitest";
import { clampPage, pageButtons, showingRange, slicePage, totalPages } from "./pagination";

describe("pagination", () => {
  it("draws the Customers bar for 366 rows: 1 2 3 4 … 15", () => {
    expect(totalPages(366)).toBe(15);
    expect(pageButtons(1, 15)).toEqual([1, 2, 3, 4, "...", 15]);
    expect(showingRange(1, 366)).toEqual({ from: 1, to: 25 });
  });

  it("shows the last partial page correctly", () => {
    expect(showingRange(15, 366)).toEqual({ from: 351, to: 366 });
    expect(pageButtons(15, 15)).toEqual([1, "...", 12, 13, 14, 15]);
  });

  it("puts dots on both sides in the middle", () => {
    expect(pageButtons(8, 15)).toEqual([1, "...", 5, 6, 7, 8, 9, 10, 11, "...", 15]);
  });

  it("has a single page for short lists", () => {
    expect(pageButtons(1, 1)).toEqual([1]);
    expect(showingRange(1, 3)).toEqual({ from: 1, to: 3 });
  });

  it("puts row 26 on page 2", () => {
    const rows = Array.from({ length: 30 }, (_, i) => i + 1);
    expect(slicePage(rows, 1)).toHaveLength(25);
    expect(slicePage(rows, 2)).toEqual([26, 27, 28, 29, 30]);
  });

  it("steps back when the list shrinks under the current page", () => {
    expect(clampPage(5, 30)).toBe(2);
    expect(clampPage(3, 0)).toBe(1);
    expect(slicePage([1, 2, 3], 4)).toEqual([1, 2, 3]);
  });
});

describe("pagination on phones", () => {
  it("keeps one page either side so the bar fits", () => {
    expect(pageButtons(8, 15, 1)).toEqual([1, "...", 7, 8, 9, "...", 15]);
    expect(pageButtons(1, 15, 1)).toEqual([1, 2, "...", 15]);
  });
});
