import { apiFetch } from "@/lib/api";

/** v9.2 #168: add a website link to the Knowledge Base, and "Undo last change" on the Brain page. */

export type KnowledgeWebDoc = { id: string; name: string; status: string };

export const knowledgeWebApi = {
  addWebsite: (url: string) =>
    apiFetch<KnowledgeWebDoc>("/api/v1/knowledge/add-website", { method: "POST", body: JSON.stringify({ url }) }),
  undoPreview: () => apiFetch<UndoPreview>("/api/v1/knowledge/undo-last"),
  /** Sends the version the screen showed: the server refuses (409) if the newest change is no longer that one. */
  undo: (versionId: string) =>
    apiFetch<{ success: boolean; kind: string; label: string }>("/api/v1/knowledge/undo-last", {
      method: "POST",
      body: JSON.stringify({ version_id: versionId }),
    }),
};

export type UndoPreview =
  | { available: false }
  | { available: true; version_id: string; kind: "description" | "facts"; label: string; changed_at: string };

/** What the Undo confirm box says: what will be put back, in plain words. */
export function undoQuestion(p: UndoPreview): string {
  if (!p.available) return "";
  const what = p.kind === "description" ? "your business Description" : `the facts of ${p.label}`;
  return `Put back ${what} as it was before the last change? Anril keeps this change in History, so you can undo the undo.`;
}

/** A website address the owner typed, tidied for the box: spaces trimmed, https added when missing. */
export function tidyWebsite(raw: string): string {
  const t = raw.trim();
  if (!t) return "";
  return /^[a-z][a-z0-9+.-]*:\/\//i.test(t) ? t : `https://${t}`;
}
