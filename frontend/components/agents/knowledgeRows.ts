import type { KbDocument, KbPage } from "@/lib/api";

export type KbDocState = "reading" | "ready" | "gaps" | "failed";

/** Where a book is: still reading, ready, ready with some pages failed, or failed. */
export function docState(doc: Pick<KbDocument, "status">): KbDocState {
  if (doc.status === "ready") return "ready";
  if (doc.status === "ready_with_gaps") return "gaps";
  if (doc.status === "failed") return "failed";
  return "reading";
}

export const KB_ACCEPT = ".txt,.md,.json,.pdf,.docx,.pptx,.xlsx,.csv,.png,.jpg,.jpeg";

/** The file types shown as chips on the upload card. MP4 is announced but not read yet. */
export const KB_TYPE_CHIPS: { label: string; later?: boolean }[] = [
  { label: "TXT" },
  { label: "MD" },
  { label: "JSON" },
  { label: "PDF" },
  { label: "DOCX" },
  { label: "PPTX" },
  { label: "XLSX" },
  { label: "CSV" },
  { label: "PNG" },
  { label: "JPG" },
  { label: "MP4", later: true },
];

/** "319 of 320 pages, 1 failed", "48 of 48 pages", "Counting pages…" before the count is known. */
export function pagesText(doc: { pages_ok: number; page_count: number; pages_failed: number }): string {
  if (doc.page_count <= 0) return "Counting pages…";
  const base = `${doc.pages_ok} of ${doc.page_count} ${doc.page_count === 1 ? "page" : "pages"}`;
  return doc.pages_failed > 0 ? `${base}, ${doc.pages_failed} failed` : base;
}

export function docStateLabel(state: KbDocState): string {
  if (state === "reading") return "Reading…";
  if (state === "gaps") return "Ready with gaps";
  if (state === "failed") return "Failed";
  return "Ready";
}

const MAX_FAILED_PARTS = 8;

/** [3,4,5,9] -> "pages 3-5, 9". Past 8 parts: the first 8, then "and N more". */
export function failedPagesText(pages: number[]): string {
  const sorted = Array.from(new Set(pages)).sort((a, b) => a - b);
  if (sorted.length === 0) return "";
  const parts: string[] = [];
  let start = sorted[0];
  let prev = sorted[0];
  for (const n of [...sorted.slice(1), Number.NaN]) {
    if (n === prev + 1) {
      prev = n;
      continue;
    }
    parts.push(start === prev ? String(start) : `${start}-${prev}`);
    start = n;
    prev = n;
  }
  const shown = parts.slice(0, MAX_FAILED_PARTS).join(", ");
  const more = parts.length - MAX_FAILED_PARTS;
  const label = sorted.length === 1 ? "page" : "pages";
  return more > 0 ? `${label} ${shown} and ${more} more` : `${label} ${shown}`;
}

/** 1536 -> "1.5 KB", 52428800 -> "50 MB". */
export function fileSizeText(bytes: number): string {
  const units = ["B", "KB", "MB", "GB"];
  let value = Math.max(0, bytes);
  let unit = 0;
  while (unit < units.length - 1 && Math.round(value * 10) / 10 >= 1024) {
    value /= 1024;
    unit += 1;
  }
  const rounded = unit === 0 ? Math.round(value) : Math.round(value * 10) / 10;
  return `${rounded} ${units[unit]}`;
}

/** null when the file fits, else "Book 7.pdf is 62 MB. The limit is 50 MB." */
export function tooLargeMessage(file: { name: string; size: number }, maxBytes: number): string | null {
  if (file.size <= maxBytes) return null;
  return `${file.name} is ${fileSizeText(file.size)}. The limit is ${fileSizeText(maxBytes)}.`;
}

/** "Book 7.PDF" -> "pdf". null when the extension is not one we read. */
export function fileTypeOf(name: string): string | null {
  const dot = name.lastIndexOf(".");
  if (dot < 0) return null;
  const ext = name.slice(dot + 1).toLowerCase();
  return KB_ACCEPT.split(",").includes(`.${ext}`) ? ext : null;
}

/** True while any book is still being read; the page polls while this is true. */
export function anyReading(docs: Pick<KbDocument, "status">[]): boolean {
  return docs.some((d) => d.status === "processing");
}

/** "Typed" (the file had text), "Scanned" (read from the picture), "" until the page is read. */
export function pageMethodLabel(p: Pick<KbPage, "method" | "status">): string {
  if (p.status !== "ok") return "";
  if (p.method === "text_layer") return "Typed";
  if (p.method === "ocr") return "Scanned";
  return "";
}

/** "Book 3, p. 88" / "Book 3, pp. 88-90" / "Book 3, p. 88, pp. 90-92". */
export function sourceText(s: { document_title: string; pages: { page_from: number; page_to: number }[] }): string {
  const ranges = s.pages.map((p) => (p.page_from === p.page_to ? `p. ${p.page_from}` : `pp. ${p.page_from}-${p.page_to}`));
  return [s.document_title, ...ranges].join(", ");
}
