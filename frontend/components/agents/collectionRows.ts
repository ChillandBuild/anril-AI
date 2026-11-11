import type { KbCollection, KbDocument, KbPage } from "@/lib/api";
import { failedPagesText } from "./knowledgeRows";

/** Display rules for the Collections pages. Pure, so they can be tested without a browser. */

export type CollectionTab = "books" | "shortcuts" | "gaps";
export const COLLECTION_TABS: { id: CollectionTab; label: string }[] = [
  { id: "books", label: "Books" },
  { id: "shortcuts", label: "Learned shortcuts" },
  { id: "gaps", label: "Missing answers" },
];

/** "?tab=gaps" -> "gaps". Anything unknown (or missing) is the Books tab. */
export function parseTab(value: string | null | undefined): CollectionTab {
  return COLLECTION_TABS.find((t) => t.id === value)?.id ?? "books";
}

/**
 * Which tab gets focus after an arrow key (WAI-ARIA tabs). Left and right wrap round;
 * Home and End jump to the ends. null for any other key.
 */
export function nextTabIndex(current: number, key: string, count: number): number | null {
  if (count <= 0) return null;
  if (key === "ArrowRight") return (current + 1) % count;
  if (key === "ArrowLeft") return (current - 1 + count) % count;
  if (key === "Home") return 0;
  if (key === "End") return count - 1;
  return null;
}

/** "3 books", "1 book", "No books yet". */
export function booksText(count: number): string {
  if (count <= 0) return "No books yet";
  return count === 1 ? "1 book" : `${count} books`;
}

/** "212 of 320 pages read", "No pages yet" for an empty collection. */
export function collectionPagesText(c: Pick<KbCollection, "pages_ok" | "page_count">): string {
  if (c.page_count <= 0) return "No pages yet";
  return `${c.pages_ok} of ${c.page_count} ${c.page_count === 1 ? "page" : "pages"} read`;
}

/** "Guru, Meena" or "No character reads this yet". */
export function readByText(readBy: { name: string }[]): string {
  if (readBy.length === 0) return "No character reads this yet";
  return readBy.map((c) => c.name).join(", ");
}

/** A collection can only be deleted while it holds no books. */
export function canDeleteCollection(c: Pick<KbCollection, "book_count">): boolean {
  return c.book_count === 0;
}

/** null when the name is fine, else the message to show under the box. */
export function nameProblem(name: string): string | null {
  return name.trim() ? null : "Type a name for the collection.";
}

/** Main resource first, then the order the server gave (newest first). Does not change the input. */
export function sortBooks<T extends Pick<KbDocument, "tier">>(docs: T[]): T[] {
  return docs
    .map((doc, index) => ({ doc, index }))
    .sort((a, b) => a.doc.tier - b.doc.tier || a.index - b.index)
    .map((x) => x.doc);
}

/** Retry is offered when some pages failed or the whole book failed. */
export function needsRetry(doc: Pick<KbDocument, "pages_failed" | "status">): boolean {
  return doc.pages_failed > 0 || doc.status === "failed";
}

/**
 * What went wrong with a book, in words. "Could not read pages 3-5, 9" when pages failed,
 * else the book's own error, else null. A book that failed outright with an error and
 * with failed pages shows both.
 */
export function problemText(doc: Pick<KbDocument, "failed_pages" | "error" | "status">): string | null {
  const parts: string[] = [];
  if (doc.failed_pages.length > 0) parts.push(`Could not read ${failedPagesText(doc.failed_pages)}`);
  if (doc.error && (doc.status === "failed" || doc.failed_pages.length === 0)) parts.push(doc.error);
  return parts.length > 0 ? parts.join(". ") : null;
}

/** The button that flips a book between main resource (tier 1) and ordinary book (tier 2). */
export function tierToggle(tier: 1 | 2): { label: string; next: 1 | 2 } {
  return tier === 1 ? { label: "Make an ordinary book", next: 2 } : { label: "Make main resource", next: 1 };
}

export function tierLabel(tier: 1 | 2): string {
  return tier === 1 ? "Main resource" : "Book";
}

export function sourceLabel(source: KbDocument["source"]): string {
  if (source === "sales_copy") return "Copied from Anril Sales";
  if (source === "owner_answers") return "Owner answers";
  return "Uploaded";
}

/** "Used 1 time", "Used 14 times". */
export function usedText(uses: number): string {
  return uses === 1 ? "Used 1 time" : `Used ${uses} times`;
}

/** "Asked 1 time this month", "Asked 6 times this month". */
export function askedText(count: number): string {
  return count === 1 ? "Asked 1 time this month" : `Asked ${count} times this month`;
}

/** "p. 88" or "pp. 88-90" for a passage's page span. */
export function pageSpanText(from: number, to: number): string {
  return from === to ? `p. ${from}` : `pp. ${from}-${to}`;
}

export type PageFilter = "all" | "failed" | "scanned";

export function filterPages<T extends Pick<KbPage, "status" | "method">>(pages: T[], filter: PageFilter): T[] {
  if (filter === "failed") return pages.filter((p) => p.status === "failed");
  if (filter === "scanned") return pages.filter((p) => p.status === "ok" && p.method === "ocr");
  return pages;
}

/** "OK", "Failed" or "Waiting" (not read yet). Colour is never the only signal. */
export function pageStatusLabel(status: KbPage["status"]): string {
  if (status === "ok") return "OK";
  if (status === "failed") return "Failed";
  return "Waiting";
}

/** "1,432 letters" for a read page, "" otherwise. */
export function lettersText(p: Pick<KbPage, "status" | "char_count">): string {
  if (p.status !== "ok") return "";
  return `${p.char_count.toLocaleString("en-IN")} ${p.char_count === 1 ? "letter" : "letters"}`;
}

/** True when the page list has a failed page, so the Retry button is worth showing. */
export function anyPageFailed(pages: Pick<KbPage, "status">[]): boolean {
  return pages.some((p) => p.status === "failed");
}

/** "Showing 100 of 412" while the list is cut short; null once everything is shown. */
export function showingText(shown: number, total: number): string | null {
  return shown < total ? `Showing ${shown} of ${total}` : null;
}

/** The API answers 404 for an id that is not this business's. */
export function isNotFound(err: unknown): boolean {
  return typeof err === "object" && err !== null && (err as { status?: number }).status === 404;
}

/** The address of the upload page with a collection already picked. */
export function importHref(collectionId: string): string {
  return `/dashboard/agents/knowledge?collection=${encodeURIComponent(collectionId)}`;
}

export function collectionHref(collectionId: string, tab?: CollectionTab): string {
  const base = `/dashboard/agents/collections/${encodeURIComponent(collectionId)}`;
  return tab && tab !== "books" ? `${base}?tab=${tab}` : base;
}

export function bookHref(collectionId: string, documentId: string): string {
  return `${collectionHref(collectionId)}/${encodeURIComponent(documentId)}`;
}
