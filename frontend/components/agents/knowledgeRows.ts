export type KnowledgeTag = { id: string; name: string; color?: string };
export type KnowledgeDocLite = {
  id: string;
  name: string;
  status: string;
  created_at: string;
  campaign_tag_id?: string | null;
  sort_state?: string | null;
  error_message?: string | null;
};
export type CharacterLite = { id: string; name: string; knowledge_tag_id: string | null };

export type TagRow = { id: string; name: string; files: number; readBy: string[]; updated: string | null };

/**
 * One row per tag that has files or a character reading it. Example:
 * "astrology books", 3 files, read by Jothidar AI, updated 9 Nov.
 */
export function tagRows(tags: KnowledgeTag[], docs: KnowledgeDocLite[], characters: CharacterLite[]): TagRow[] {
  return tags
    .map((tag) => {
      const tagged = docs.filter((d) => d.campaign_tag_id === tag.id);
      const updated = tagged.reduce<string | null>((max, d) => (!max || d.created_at > max ? d.created_at : max), null);
      return {
        id: tag.id,
        name: tag.name,
        files: tagged.length,
        readBy: characters.filter((c) => c.knowledge_tag_id === tag.id).map((c) => c.name),
        updated,
      };
    })
    .filter((row) => row.files > 0 || row.readBy.length > 0)
    .sort((a, b) => b.files - a.files || a.name.localeCompare(b.name));
}

export type DocState = "processing" | "ready" | "failed";

export function docState(doc: Pick<KnowledgeDocLite, "status" | "sort_state">): DocState {
  if (doc.status === "failed" || doc.sort_state === "failed") return "failed";
  if (doc.status === "processing" || doc.sort_state === "sorting") return "processing";
  return "ready";
}

export const ACCEPT = ".pdf,.docx,.doc,.pptx,.ppt,.xlsx,.xls,.csv,.txt,.md,.markdown";
