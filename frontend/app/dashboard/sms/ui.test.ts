import { describe, expect, it } from "vitest";
import { MAX_UPLOAD_BYTES, acceptList, fileProblem, formatFileSize } from "./ui";

describe("formatFileSize", () => {
  it("shows B, KB and MB", () => {
    expect(formatFileSize(500)).toBe("500 B");
    expect(formatFileSize(18 * 1024)).toBe("18 KB");
    expect(formatFileSize(2.5 * 1024 * 1024)).toBe("2.5 MB");
    expect(formatFileSize(MAX_UPLOAD_BYTES)).toBe("20 MB");
  });
});

describe("fileProblem", () => {
  it("accepts a right-type file under the limit, ignoring case", () => {
    expect(fileProblem({ name: "Senders.XLSX", size: 1000 }, ".xlsx,.csv")).toBeNull();
  });
  it("refuses a wrong extension", () => {
    expect(fileProblem({ name: "a.pdf", size: 10 }, ".xlsx,.csv")).toMatch(/isn't a supported file/);
  });
  it("refuses a file over the limit and allows exactly the limit", () => {
    expect(fileProblem({ name: "a.csv", size: MAX_UPLOAD_BYTES + 1 }, ".csv")).toMatch(/limit is 20 MB/);
    expect(fileProblem({ name: "a.csv", size: MAX_UPLOAD_BYTES }, ".csv")).toBeNull();
  });
});

describe("acceptList", () => {
  it("normalises the accept string", () => {
    expect(acceptList(".XLSX, csv")).toEqual([".xlsx", ".csv"]);
  });
});
