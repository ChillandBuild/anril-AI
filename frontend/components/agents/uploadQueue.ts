import type { KbCollection, KbDocument, KbUploadTicket } from "@/lib/api";
import { KB_TYPE_CHIPS, fileTypeOf, tooLargeMessage } from "@/components/agents/knowledgeRows";

/** Pure helpers for the Upload page: file checks, the upload steps, the collection list, recent files. */

/** "Book 7.pdf" -> "Book 7". A name with no extension, or only a leading dot, is kept whole. */
export function titleFromFileName(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(0, dot) : name;
}

function typeList(): string {
  return KB_TYPE_CHIPS.filter((c) => !c.later)
    .map((c) => c.label)
    .join(", ");
}

/** null when the file can be uploaded, else a plain sentence saying why not. */
export function checkFile(file: { name: string; size: number }, maxBytes: number | null): string | null {
  if (fileTypeOf(file.name) === null) {
    return `${file.name} is a type we cannot read yet. Use ${typeList()}.`;
  }
  if (file.size <= 0) return `${file.name} is empty.`;
  return maxBytes === null ? null : tooLargeMessage(file, maxBytes);
}

/** Splits picked files into the ones to stage and one message per refused file. Same name and size twice is added once, and the repeat is reported. */
export function sortPickedFiles<T extends { name: string; size: number }>(
  picked: T[],
  alreadyStaged: { name: string; size: number }[],
  maxBytes: number | null,
): { accepted: T[]; refused: string[] } {
  const accepted: T[] = [];
  const refused: string[] = [];
  const seen = [...alreadyStaged];
  for (const f of picked) {
    if (seen.some((s) => s.name === f.name && s.size === f.size)) {
      const again = `${f.name} is already in the list`;
      if (!refused.includes(again)) refused.push(again);
      continue;
    }
    const problem = checkFile(f, maxBytes);
    if (problem) {
      refused.push(problem);
      continue;
    }
    accepted.push(f);
    seen.push(f);
  }
  return { accepted, refused };
}

export type UploadStep = "uploading" | "registering";

/** The calls the upload needs. companionKbApi satisfies this; tests pass fakes. */
export type UploadApi = {
  createUpload: (name: string, sizeBytes: number) => Promise<KbUploadTicket>;
  uploadToTicket: (ticket: KbUploadTicket, file: File, onProgress?: (fraction: number) => void) => Promise<void>;
  registerDocument: (body: { draft_id: string; collection_id: string; tier: 1 | 2; title?: string }) => Promise<KbDocument>;
};

/**
 * One file, three steps: ask for a ticket, send the file, register it as a file.
 * Throws the first error; the caller shows it on that file only.
 */
export async function uploadOne(
  api: UploadApi,
  file: File,
  target: { collectionId: string; tier: 1 | 2 },
  hooks: { onStep?: (step: UploadStep) => void; onProgress?: (fraction: number) => void } = {},
): Promise<KbDocument> {
  hooks.onStep?.("uploading");
  const ticket = await api.createUpload(file.name, file.size);
  await api.uploadToTicket(ticket, file, hooks.onProgress);
  hooks.onStep?.("registering");
  return api.registerDocument({
    draft_id: ticket.draft_id,
    collection_id: target.collectionId,
    tier: target.tier,
    title: titleFromFileName(file.name).slice(0, 200),   // the server rejects longer titles after the upload is done
  });
}

export type UploadItem = {
  id: string;
  file: File;
  status: "staged" | "uploading" | "registering" | "done" | "error";
  /** 0 to 1 while uploading. */
  progress: number;
  error: string;
  /** Fixed when Import is pressed, so Retry goes to the same place. */
  collectionId: string | null;
  tier: 1 | 2 | null;
};

/** What to show beside a file: "Waiting", "Uploading 40%", "Saving", "Added", or the error. */
export function itemStatusText(item: Pick<UploadItem, "status" | "progress" | "error">): string {
  switch (item.status) {
    case "staged":
      return "Ready to import";
    case "uploading":
      return `Uploading ${Math.round(Math.min(1, Math.max(0, item.progress)) * 100)}%`;
    case "registering":
      return "Saving";
    case "done":
      return "Added. Reading starts now.";
    default:
      return item.error || "Could not upload this file.";
  }
}

export function stagedCount(items: Pick<UploadItem, "status">[]): number {
  return items.filter((i) => i.status === "staged").length;
}

export function isBusy(items: Pick<UploadItem, "status">[]): boolean {
  return items.some((i) => i.status === "uploading" || i.status === "registering");
}

/** "Import" / "Import 3 files". */
export function importLabel(count: number): string {
  return count > 1 ? `Import ${count} files` : "Import";
}

// ---- collection picker ----

/** Collections whose name contains the typed text, case-insensitively. */
export function filterCollections(collections: KbCollection[], query: string): KbCollection[] {
  const q = query.trim().toLowerCase();
  return q ? collections.filter((c) => c.name.toLowerCase().includes(q)) : collections;
}

/** True when the typed name is new, so the list should offer Create "name". */
export function canCreateCollection(collections: KbCollection[], query: string): boolean {
  const q = query.trim().toLowerCase();
  return q.length > 0 && !collections.some((c) => c.name.trim().toLowerCase() === q);
}

/** Move the highlighted option by one, wrapping at both ends. -1 means nothing is highlighted yet. */
export function moveIndex(current: number, delta: 1 | -1, count: number): number {
  if (count <= 0) return -1;
  if (current < 0) return delta === 1 ? 0 : count - 1;
  return (current + delta + count) % count;
}

/**
 * The option Enter would pick right after typing: the first match if there is one,
 * else the Create option (which then sits at index 0), else nothing.
 */
export function defaultIndex(matchCount: number, createOffered: boolean): number {
  if (matchCount > 0) return 0;
  return createOffered ? 0 : -1;
}

// ---- lists on the page ----

/** Files being read, oldest first so a row does not jump when a newer one is added. */
export function processingBooks(docs: KbDocument[]): KbDocument[] {
  return docs
    .filter((d) => d.status === "processing")
    .sort((a, b) => a.created_at.localeCompare(b.created_at));
}

/** The newest files, any status. */
export function recentBooks(docs: KbDocument[], count = 5): KbDocument[] {
  return [...docs].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, count);
}

/** Link to one file's screen. */
export function bookHref(doc: Pick<KbDocument, "collection_id" | "id">): string {
  return `/dashboard/agents/collections/${doc.collection_id}/${doc.id}`;
}

/** Add or drop an id from a selection, keeping order. */
export function toggleId(ids: string[], id: string): string[] {
  return ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id];
}
