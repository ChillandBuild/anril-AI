import { describe, expect, it, vi } from "vitest";
import { UploadCancelledError, type KbCollection, type KbDocument, type KbUploadTicket } from "@/lib/api";
import {
  CANCELLED_TEXT,
  bookHref,
  canCreateCollection,
  checkFile,
  defaultIndex,
  filterCollections,
  importLabel,
  isBusy,
  itemStatusText,
  moveIndex,
  processingBooks,
  recentBooks,
  sortPickedFiles,
  stagedCount,
  titleFromFileName,
  toggleId,
  uploadOne,
  type UploadApi,
} from "./uploadQueue";

const MB = 1024 * 1024;
const col = (id: string, name: string): KbCollection => ({
  id,
  name,
  book_count: 0,
  page_count: 0,
  pages_ok: 0,
  read_by: [],
  created_at: "",
  updated_at: "",
});
const doc = (id: string, created_at: string, status: KbDocument["status"] = "ready"): KbDocument => ({
  id,
  collection_id: "c1",
  collection_name: "Product guides",
  title: id,
  file_type: "pdf",
  size_bytes: 1,
  tier: 2,
  page_count: 10,
  status,
  source: "upload",
  error: null,
  pages_ok: 10,
  pages_failed: 0,
  pages_pending: 0,
  failed_pages: [],
  created_at,
  updated_at: created_at,
});

describe("titleFromFileName", () => {
  it("drops the extension only", () => {
    expect(titleFromFileName("Book 7.pdf")).toBe("Book 7");
    expect(titleFromFileName("notes.final.md")).toBe("notes.final");
    expect(titleFromFileName("README")).toBe("README");
    expect(titleFromFileName(".hidden")).toBe(".hidden");
  });
});

describe("checkFile", () => {
  it("accepts a file that fits", () => {
    expect(checkFile({ name: "Book 7.pdf", size: 10 * MB }, 50 * MB)).toBeNull();
    expect(checkFile({ name: "Book 7.pdf", size: 10 * MB }, null)).toBeNull();
  });
  it("refuses a file over the limit with the size message", () => {
    expect(checkFile({ name: "Book 7.pdf", size: 62 * MB }, 50 * MB)).toBe("Book 7.pdf is 62 MB. The limit is 50 MB.");
  });
  it("refuses an unknown type and names the types we read", () => {
    const msg = checkFile({ name: "movie.mp4", size: 5 }, 50 * MB);
    expect(msg).toContain("movie.mp4");
    expect(msg).toContain("PDF");
    expect(msg).not.toContain("MP4,");
  });
  it("refuses an empty file", () => {
    expect(checkFile({ name: "a.txt", size: 0 }, 50 * MB)).toBe("a.txt is empty.");
  });
});

describe("sortPickedFiles", () => {
  it("accepts good files, reports each bad one, reports a repeat once", () => {
    const picked = [
      { name: "a.pdf", size: 5 },
      { name: "a.pdf", size: 5 },
      { name: "b.mp4", size: 5 },
      { name: "c.pdf", size: 99 * MB },
      { name: "d.pdf", size: 7 },
    ];
    const r = sortPickedFiles(picked, [{ name: "d.pdf", size: 7 }], 50 * MB);
    expect(r.accepted.map((f) => f.name)).toEqual(["a.pdf"]);
    expect(r.refused).toHaveLength(4);
    expect(r.refused).toContain("a.pdf is already in the list");
    expect(r.refused).toContain("d.pdf is already in the list");
  });
});

function fakeApi(overrides: Partial<UploadApi> = {}): UploadApi & { calls: string[] } {
  const calls: string[] = [];
  const ticket: KbUploadTicket = { draft_id: "d1", upload_url: "u", token: "t", path: "p", file_type: "pdf" };
  return {
    calls,
    createUpload: async (name, size) => {
      calls.push(`create ${name} ${size}`);
      return ticket;
    },
    uploadToTicket: async (_t, _f, onProgress) => {
      calls.push("send");
      onProgress?.(1);
    },
    registerDocument: async (body) => {
      calls.push(`register ${body.draft_id} ${body.collection_id} ${body.tier} ${body.title}`);
      return doc("new", "2026-11-11T00:00:00Z", "processing");
    },
    ...overrides,
  };
}

describe("uploadOne", () => {
  it("asks for a ticket, sends the file, then registers it with the title", async () => {
    const api = fakeApi();
    const steps: string[] = [];
    const file = new File(["x"], "Book 7.pdf");
    await uploadOne(api, file, { collectionId: "c1", tier: 1 }, { onStep: (s) => steps.push(s) });
    expect(api.calls).toEqual(["create Book 7.pdf 1", "send", "register d1 c1 1 Book 7"]);
    expect(steps).toEqual(["uploading", "registering"]);
  });
  it("cuts a very long file name to 200 characters for the title", async () => {
    const api = fakeApi();
    await uploadOne(api, new File(["x"], `${"a".repeat(250)}.pdf`), { collectionId: "c1", tier: 1 });
    expect(api.calls[2]).toBe(`register d1 c1 1 ${"a".repeat(200)}`);
  });
  it("stops at the first error and does not register", async () => {
    const api = fakeApi({ uploadToTicket: vi.fn().mockRejectedValue(new Error("Upload failed (500). Please try again.")) });
    const register = vi.spyOn(api, "registerDocument");
    await expect(uploadOne(api, new File(["x"], "a.pdf"), { collectionId: "c1", tier: 2 })).rejects.toThrow("Upload failed");
    expect(register).not.toHaveBeenCalled();
  });
  it("Cancel while sending: passes the signal on, throws UploadCancelledError, never registers", async () => {
    const controller = new AbortController();
    let seen: AbortSignal | undefined;
    const api = fakeApi({
      uploadToTicket: vi.fn(async (_t, _f, _p, signal?: AbortSignal) => {
        seen = signal;
        controller.abort();                      // the person presses Cancel at 40%
        throw new UploadCancelledError();
      }),
    });
    const register = vi.spyOn(api, "registerDocument");
    const run = uploadOne(api, new File(["x"], "01 Kumaraswamiyam.pdf"), { collectionId: "c1", tier: 2 }, { signal: controller.signal });
    await expect(run).rejects.toBeInstanceOf(UploadCancelledError);
    expect(seen).toBe(controller.signal);
    expect(register).not.toHaveBeenCalled();
  });
  it("Cancel pressed just as the file finished sending: still not registered", async () => {
    const controller = new AbortController();
    const api = fakeApi({ uploadToTicket: vi.fn(async () => controller.abort()) });
    const register = vi.spyOn(api, "registerDocument");
    await expect(
      uploadOne(api, new File(["x"], "a.pdf"), { collectionId: "c1", tier: 2 }, { signal: controller.signal }),
    ).rejects.toBeInstanceOf(UploadCancelledError);
    expect(register).not.toHaveBeenCalled();
  });
});

describe("itemStatusText and counts", () => {
  it("says what is happening to a file", () => {
    expect(itemStatusText({ status: "staged", progress: 0, error: "" })).toBe("Ready to import");
    expect(itemStatusText({ status: "staged", progress: 0, error: CANCELLED_TEXT })).toBe("Upload cancelled. Press Import to try again.");
    expect(itemStatusText({ status: "uploading", progress: 0.404, error: "" })).toBe("Uploading 40%");
    expect(itemStatusText({ status: "registering", progress: 1, error: "" })).toBe("Saving");
    expect(itemStatusText({ status: "done", progress: 1, error: "" })).toBe("Added. Reading starts now.");
    expect(itemStatusText({ status: "error", progress: 0, error: "Name taken" })).toBe("Name taken");
    expect(itemStatusText({ status: "error", progress: 0, error: "" })).toBe("Could not upload this file.");
  });
  it("counts staged files and notices work in progress", () => {
    const items = [{ status: "staged" as const }, { status: "error" as const }, { status: "staged" as const }];
    expect(stagedCount(items)).toBe(2);
    expect(isBusy(items)).toBe(false);
    expect(isBusy([...items, { status: "uploading" as const }])).toBe(true);
    expect(isBusy([{ status: "registering" as const }])).toBe(true);
  });
  it("labels the Import button", () => {
    expect(importLabel(0)).toBe("Import");
    expect(importLabel(1)).toBe("Import");
    expect(importLabel(3)).toBe("Import 3 files");
  });
});

describe("collection picker helpers", () => {
  const cols = [col("a", "Product guides"), col("r", "Remedies")];
  it("filters by typed text", () => {
    expect(filterCollections(cols, "")).toHaveLength(2);
    expect(filterCollections(cols, "  product ").map((c) => c.id)).toEqual(["a"]);
    expect(filterCollections(cols, "zzz")).toEqual([]);
  });
  it("offers Create only for a new name", () => {
    expect(canCreateCollection(cols, "")).toBe(false);
    expect(canCreateCollection(cols, "remedies")).toBe(false);
    expect(canCreateCollection(cols, "Vastu")).toBe(true);
    expect(canCreateCollection(cols, "Astro")).toBe(true);
  });
  it("moves the highlight and wraps", () => {
    expect(moveIndex(-1, 1, 3)).toBe(0);
    expect(moveIndex(-1, -1, 3)).toBe(2);
    expect(moveIndex(2, 1, 3)).toBe(0);
    expect(moveIndex(0, -1, 3)).toBe(2);
    expect(moveIndex(0, 1, 0)).toBe(-1);
  });
  it("starts on the first match, else on Create, else nothing", () => {
    expect(defaultIndex(2, true)).toBe(0);
    expect(defaultIndex(0, true)).toBe(0);
    expect(defaultIndex(0, false)).toBe(-1);
  });
});

describe("lists", () => {
  const docs = [
    doc("old", "2026-11-01T00:00:00Z"),
    doc("mid", "2026-11-05T00:00:00Z", "processing"),
    doc("new", "2026-11-09T00:00:00Z", "processing"),
    doc("x1", "2026-11-02T00:00:00Z"),
    doc("x2", "2026-11-03T00:00:00Z"),
    doc("x3", "2026-11-04T00:00:00Z"),
  ];
  it("lists books being read, oldest first", () => {
    expect(processingBooks(docs).map((d) => d.id)).toEqual(["mid", "new"]);
  });
  it("lists the newest 5, newest first", () => {
    expect(recentBooks(docs).map((d) => d.id)).toEqual(["new", "mid", "x3", "x2", "x1"]);
    expect(recentBooks(docs, 2)).toHaveLength(2);
  });
  it("does not change the list it is given", () => {
    const copy = [...docs];
    recentBooks(docs);
    processingBooks(docs);
    expect(docs).toEqual(copy);
  });
  it("links to the book screen", () => {
    expect(bookHref({ collection_id: "c1", id: "d9" })).toBe("/dashboard/agents/collections/c1/d9");
  });
  it("toggles an id", () => {
    expect(toggleId(["a"], "b")).toEqual(["a", "b"]);
    expect(toggleId(["a", "b"], "a")).toEqual(["b"]);
  });
});
