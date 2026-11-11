import { describe, expect, it } from "vitest";
import {
  anyPageFailed,
  askedText,
  bookHref,
  booksText,
  canDeleteCollection,
  collectionHref,
  collectionPagesText,
  filterPages,
  importHref,
  isNotFound,
  lettersText,
  needsRetry,
  nameProblem,
  nextTabIndex,
  pageSpanText,
  pageStatusLabel,
  parseTab,
  problemText,
  readByText,
  showingText,
  sortBooks,
  sourceLabel,
  tierToggle,
  usedText,
} from "./collectionRows";

describe("parseTab", () => {
  it("keeps a known tab and falls back to books", () => {
    expect(parseTab("gaps")).toBe("gaps");
    expect(parseTab("shortcuts")).toBe("shortcuts");
    expect(parseTab("nonsense")).toBe("books");
    expect(parseTab(null)).toBe("books");
  });
});

describe("nextTabIndex", () => {
  it("wraps with the arrow keys and jumps with Home and End", () => {
    expect(nextTabIndex(0, "ArrowRight", 3)).toBe(1);
    expect(nextTabIndex(2, "ArrowRight", 3)).toBe(0);
    expect(nextTabIndex(0, "ArrowLeft", 3)).toBe(2);
    expect(nextTabIndex(1, "Home", 3)).toBe(0);
    expect(nextTabIndex(1, "End", 3)).toBe(2);
  });
  it("ignores other keys", () => {
    expect(nextTabIndex(1, "Enter", 3)).toBeNull();
    expect(nextTabIndex(0, "ArrowRight", 0)).toBeNull();
  });
});

describe("collection rows", () => {
  it("says how many books and pages", () => {
    expect(booksText(0)).toBe("No files yet");
    expect(booksText(1)).toBe("1 file");
    expect(booksText(17)).toBe("17 files");
    expect(collectionPagesText({ pages_ok: 212, page_count: 320 })).toBe("212 of 320 pages read");
    expect(collectionPagesText({ pages_ok: 0, page_count: 0 })).toBe("No pages yet");
  });
  it("names the characters that read a collection", () => {
    expect(readByText([])).toBe("No character reads this yet");
    expect(readByText([{ name: "Maya" }, { name: "Arjun" }])).toBe("Maya, Arjun");
  });
  it("lets only an empty collection be deleted", () => {
    expect(canDeleteCollection({ book_count: 0 })).toBe(true);
    expect(canDeleteCollection({ book_count: 2 })).toBe(false);
  });
  it("refuses a blank name", () => {
    expect(nameProblem("   ")).not.toBeNull();
    expect(nameProblem(" Vastu ")).toBeNull();
  });
});

describe("book rows", () => {
  it("puts the main resource first and keeps the server order otherwise", () => {
    const docs = [
      { id: "a", tier: 2 as const },
      { id: "b", tier: 1 as const },
      { id: "c", tier: 2 as const },
    ];
    expect(sortBooks(docs).map((d) => d.id)).toEqual(["b", "a", "c"]);
    expect(docs.map((d) => d.id)).toEqual(["a", "b", "c"]);
  });
  it("offers Retry for failed pages or a failed book only", () => {
    expect(needsRetry({ pages_failed: 1, status: "ready_with_gaps" })).toBe(true);
    expect(needsRetry({ pages_failed: 0, status: "failed" })).toBe(true);
    expect(needsRetry({ pages_failed: 0, status: "ready" })).toBe(false);
    expect(needsRetry({ pages_failed: 0, status: "processing" })).toBe(false);
  });
  it("describes what went wrong", () => {
    expect(problemText({ failed_pages: [44, 91], error: null, status: "ready_with_gaps" })).toBe("Could not read pages 44, 91");
    expect(problemText({ failed_pages: [], error: "The file is password protected.", status: "failed" })).toBe(
      "The file is password protected.",
    );
    expect(problemText({ failed_pages: [3], error: "Some pages failed", status: "ready_with_gaps" })).toBe("Could not read page 3");
    expect(problemText({ failed_pages: [], error: null, status: "ready" })).toBeNull();
  });
  it("flips the tier", () => {
    expect(tierToggle(2)).toEqual({ label: "Make main resource", next: 1 });
    expect(tierToggle(1)).toEqual({ label: "Make a regular file", next: 2 });
  });
  it("labels where a book came from", () => {
    expect(sourceLabel("upload")).toBe("Uploaded");
    expect(sourceLabel("sales_copy")).toBe("Copied from Anril Sales");
    expect(sourceLabel("owner_answers")).toBe("Owner answers");
  });
});

describe("shortcut and gap rows", () => {
  it("counts in plain words", () => {
    expect(usedText(1)).toBe("Used 1 time");
    expect(usedText(14)).toBe("Used 14 times");
    expect(askedText(1)).toBe("Asked 1 time this month");
    expect(askedText(6)).toBe("Asked 6 times this month");
  });
});

describe("page rows", () => {
  const pages = [
    { status: "ok" as const, method: "text_layer" as const },
    { status: "ok" as const, method: "ocr" as const },
    { status: "failed" as const, method: null },
    { status: "pending" as const, method: null },
  ];
  it("filters by failed and scanned", () => {
    expect(filterPages(pages, "all")).toHaveLength(4);
    expect(filterPages(pages, "failed")).toEqual([pages[2]]);
    expect(filterPages(pages, "scanned")).toEqual([pages[1]]);
  });
  it("labels status and size", () => {
    expect(pageStatusLabel("ok")).toBe("OK");
    expect(pageStatusLabel("failed")).toBe("Failed");
    expect(pageStatusLabel("pending")).toBe("Waiting");
    expect(lettersText({ status: "ok", char_count: 1432 })).toBe("1,432 letters");
    expect(lettersText({ status: "failed", char_count: 0 })).toBe("");
    expect(anyPageFailed(pages)).toBe(true);
    expect(anyPageFailed(pages.slice(0, 2))).toBe(false);
  });
  it("writes page spans", () => {
    expect(pageSpanText(88, 88)).toBe("p. 88");
    expect(pageSpanText(88, 90)).toBe("pp. 88-90");
    expect(showingText(100, 412)).toBe("Showing 100 of 412");
    expect(showingText(412, 412)).toBeNull();
  });
});

describe("links and errors", () => {
  it("builds the addresses", () => {
    expect(importHref("c 1")).toBe("/dashboard/agents/knowledge?collection=c%201");
    expect(collectionHref("c1")).toBe("/dashboard/agents/collections/c1");
    expect(collectionHref("c1", "gaps")).toBe("/dashboard/agents/collections/c1?tab=gaps");
    expect(collectionHref("c1", "books")).toBe("/dashboard/agents/collections/c1");
    expect(bookHref("c1", "d9")).toBe("/dashboard/agents/collections/c1/d9");
  });
  it("spots a 404", () => {
    expect(isNotFound(Object.assign(new Error("x"), { status: 404 }))).toBe(true);
    expect(isNotFound(Object.assign(new Error("x"), { status: 409 }))).toBe(false);
    expect(isNotFound(new Error("x"))).toBe(false);
    expect(isNotFound(null)).toBe(false);
  });
});
