import { describe, expect, it } from "vitest";
import {
  KB_ACCEPT,
  KB_TYPE_CHIPS,
  anyReading,
  docState,
  docStateLabel,
  failedPagesText,
  fileSizeText,
  fileTypeOf,
  pageMethodLabel,
  pagesText,
  sourceText,
  tooLargeMessage,
} from "./knowledgeRows";

describe("docState", () => {
  it("maps the four statuses", () => {
    expect(docState({ status: "processing" })).toBe("reading");
    expect(docState({ status: "ready" })).toBe("ready");
    expect(docState({ status: "ready_with_gaps" })).toBe("gaps");
    expect(docState({ status: "failed" })).toBe("failed");
  });
  it("has a label for each state", () => {
    expect(docStateLabel("reading")).toBe("Reading…");
    expect(docStateLabel("ready")).toBe("Ready");
    expect(docStateLabel("gaps")).toBe("Ready with gaps");
    expect(docStateLabel("failed")).toBe("Failed");
  });
});

describe("KB_ACCEPT and KB_TYPE_CHIPS", () => {
  it("lists the accepted extensions", () => {
    expect(KB_ACCEPT).toBe(".txt,.md,.json,.pdf,.docx,.pptx,.xlsx,.csv,.png,.jpg,.jpeg");
  });
  it("shows the types, with MP4 marked as later", () => {
    expect(KB_TYPE_CHIPS.map((c) => c.label)).toEqual(["TXT", "MD", "JSON", "PDF", "DOCX", "PPTX", "XLSX", "CSV", "PNG", "JPG", "MP4"]);
    expect(KB_TYPE_CHIPS.filter((c) => c.later).map((c) => c.label)).toEqual(["MP4"]);
  });
});

describe("pagesText", () => {
  it("says how many pages were read, and how many failed", () => {
    expect(pagesText({ pages_ok: 319, page_count: 320, pages_failed: 1 })).toBe("319 of 320 pages, 1 failed");
    expect(pagesText({ pages_ok: 48, page_count: 48, pages_failed: 0 })).toBe("48 of 48 pages");
    expect(pagesText({ pages_ok: 0, page_count: 0, pages_failed: 0 })).toBe("Counting pages…");
    expect(pagesText({ pages_ok: 1, page_count: 1, pages_failed: 0 })).toBe("1 of 1 page");
  });
});

describe("failedPagesText", () => {
  it("names the pages and collapses runs", () => {
    expect(failedPagesText([])).toBe("");
    expect(failedPagesText([200])).toBe("page 200");
    expect(failedPagesText([3, 4, 5, 9])).toBe("pages 3-5, 9");
  });
  it("sorts and de-duplicates", () => {
    expect(failedPagesText([9, 4, 3, 5, 4])).toBe("pages 3-5, 9");
  });
  it("shows the first 8 parts, then how many more", () => {
    expect(failedPagesText([1, 3, 5, 7, 9, 11, 13, 15, 17, 19])).toBe("pages 1, 3, 5, 7, 9, 11, 13, 15 and 2 more");
    expect(failedPagesText([1, 3, 5, 7, 9, 11, 13, 15])).toBe("pages 1, 3, 5, 7, 9, 11, 13, 15");
  });
});

describe("fileSizeText", () => {
  it("writes sizes the way people read them", () => {
    expect(fileSizeText(1536)).toBe("1.5 KB");
    expect(fileSizeText(52428800)).toBe("50 MB");
    expect(fileSizeText(500)).toBe("500 B");
    expect(fileSizeText(1048575)).toBe("1 MB");
  });
});

describe("tooLargeMessage", () => {
  it("is null when the file fits", () => {
    expect(tooLargeMessage({ name: "Book 7.pdf", size: 52428800 }, 52428800)).toBeNull();
  });
  it("names the file, its size and the limit when it does not", () => {
    expect(tooLargeMessage({ name: "Book 7.pdf", size: 62 * 1024 * 1024 }, 52428800)).toBe(
      "Book 7.pdf is 62 MB. The limit is 50 MB.",
    );
  });
});

describe("fileTypeOf", () => {
  it("reads the extension, case-insensitively", () => {
    expect(fileTypeOf("Book 7.PDF")).toBe("pdf");
    expect(fileTypeOf("notes.final.md")).toBe("md");
  });
  it("is null for a type we do not read", () => {
    expect(fileTypeOf("movie.mp4")).toBeNull();
    expect(fileTypeOf("README")).toBeNull();
  });
});

describe("anyReading", () => {
  it("is true while any book is still being read", () => {
    expect(anyReading([{ status: "ready" }, { status: "processing" }])).toBe(true);
    expect(anyReading([{ status: "ready" }, { status: "failed" }, { status: "ready_with_gaps" }])).toBe(false);
    expect(anyReading([])).toBe(false);
  });
});

describe("pageMethodLabel", () => {
  it("says how a page was read", () => {
    expect(pageMethodLabel({ method: "text_layer", status: "ok" })).toBe("Typed");
    expect(pageMethodLabel({ method: "ocr", status: "ok" })).toBe("Scanned");
    expect(pageMethodLabel({ method: null, status: "pending" })).toBe("");
  });
});

describe("sourceText", () => {
  it("names the book and pages", () => {
    expect(sourceText({ document_title: "Book 3", pages: [{ page_from: 88, page_to: 88 }] })).toBe("Book 3, p. 88");
    expect(sourceText({ document_title: "Book 3", pages: [{ page_from: 88, page_to: 90 }] })).toBe("Book 3, pp. 88-90");
    expect(
      sourceText({ document_title: "Book 3", pages: [{ page_from: 88, page_to: 88 }, { page_from: 90, page_to: 92 }] }),
    ).toBe("Book 3, p. 88, pp. 90-92");
    expect(sourceText({ document_title: "Book 3", pages: [] })).toBe("Book 3");
  });
});
