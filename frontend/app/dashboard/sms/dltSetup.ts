// Pure helpers for the DLT Setup page (Entity ID, Sender ID, Content Template).

export type DltSub = "entities" | "senders" | "templates";

/** The ?sub= value, defaulting to entities for anything unknown. */
export function parseDltSub(value: string | null | undefined): DltSub {
  return value === "senders" || value === "templates" ? value : "entities";
}

/**
 * Which sub-tab a setup URL opens. The page used to have top-level tabs, so old links still land sensibly:
 * ?tab=entity and ?tab=petm open Entity ID; ?tab=manager&sub=X (or just ?sub=X) opens X.
 */
export function setupSubFor(tab: string | null | undefined, sub: string | null | undefined): DltSub {
  if (tab === "entity" || tab === "petm") return "entities";
  return parseDltSub(sub);
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
