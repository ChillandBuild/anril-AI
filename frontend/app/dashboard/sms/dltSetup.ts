// Pure helpers for the DLT Setup page (Add Entity, DLT Manager, PE-TM Binding).

export type SetupTab = "entity" | "manager" | "petm";

/** The ?tab= value, defaulting to the first tab for anything unknown. */
export function parseSetupTab(value: string | null | undefined): SetupTab {
  return value === "manager" || value === "petm" ? value : "entity";
}

export type DltSub = "entities" | "senders" | "templates";

/** The ?sub= value inside DLT Manager, defaulting to entities for anything unknown. */
export function parseDltSub(value: string | null | undefined): DltSub {
  return value === "senders" || value === "templates" ? value : "entities";
}

/** "ANRILX, anrily  ANRILZ" -> ["ANRILX","ANRILY","ANRILZ"] (upper-cased, no repeats). */
export function parseSenderIds(text: string): string[] {
  const seen = new Set<string>();
  for (const part of text.split(/[\s,;]+/)) {
    const id = part.trim().toUpperCase();
    if (id) seen.add(id);
  }
  return Array.from(seen);
}

/** A sender ID (header) is 3 to 6 letters. */
export function isValidSenderId(id: string): boolean {
  return /^[A-Za-z]{3,6}$/.test(id);
}

/** Case-insensitive "any field contains the query"; an empty query matches everything. */
export function matchesQuery(fields: (string | null | undefined)[], query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return fields.some((f) => (f ?? "").toLowerCase().includes(q));
}

export const PROOF_EXTENSIONS = ["jpg", "jpeg", "png", "pdf"];

/** The PE-TM screenshot must be jpg, jpeg, png or pdf. */
export function isPeTmProof(fileName: string): boolean {
  const ext = fileName.split(".").pop()?.toLowerCase() ?? "";
  return fileName.includes(".") && PROOF_EXTENSIONS.includes(ext);
}

export interface PeTmState {
  tmApproved: boolean;
  done: boolean;
  /** The "I've done the final approval" button: only after TM approval, and only once. */
  canConfirm: boolean;
}

export function peTmState(item: { tm_approved_at: string | null; pe_confirmed_at: string | null }): PeTmState {
  const tmApproved = !!item.tm_approved_at;
  const done = !!item.pe_confirmed_at;
  return { tmApproved, done, canConfirm: tmApproved && !done };
}

/** Newest meaningful date of a PE-TM row: confirmed, else TM-approved, else uploaded. */
export function peTmDate(item: { tm_approved_at: string | null; pe_confirmed_at: string | null; created_at: string }): string {
  return item.pe_confirmed_at ?? item.tm_approved_at ?? item.created_at;
}
