import { apiFetch } from "@/lib/api";
import type { FeedbackReason } from "@/lib/aiSetupApi";

/** The thumbs-down this person already left on an AI reply, so it still shows (with Undo) after a reload. */
export type ReplyMark = { reason: FeedbackReason; note: string | null };
type MineResponse = { marks: Record<string, ReplyMark> };
export type MarksFetcher = (ids: string[]) => Promise<Record<string, ReplyMark>>;

const MAX_IDS_PER_CALL = 100;

export function chunkIds(ids: string[], size = MAX_IDS_PER_CALL): string[][] {
  const out: string[][] = [];
  for (let i = 0; i < ids.length; i += size) out.push(ids.slice(i, i + size));
  return out;
}

export function mineUrl(ids: string[]): string {
  return `/api/v1/ai-setup/reply-feedback/mine?message_ids=${ids.map(encodeURIComponent).join(",")}`;
}

const fetchMarks: MarksFetcher = async (ids) => {
  const res = await apiFetch<MineResponse>(mineUrl(ids));
  return res?.marks ?? {};
};

/**
 * Asks for the marks of every AI reply on screen in one call: each reply asks for its own id, the asks made in the
 * same moment are sent together. Answers are remembered, so a reply scrolled away and back does not ask again.
 */
export function createMarkLoader(fetcher: MarksFetcher = fetchMarks, delayMs = 40) {
  const known = new Map<string, ReplyMark | null>();
  const waiting = new Map<string, Array<(m: ReplyMark | null) => void>>();
  let timer: ReturnType<typeof setTimeout> | null = null;

  async function flush() {
    timer = null;
    const batch = new Map(waiting);
    waiting.clear();
    for (const ids of chunkIds(Array.from(batch.keys()))) {
      let marks: Record<string, ReplyMark> = {};
      let ok = true;
      try {
        marks = await fetcher(ids);
      } catch {
        ok = false; // not remembered, so the next ask tries again
      }
      for (const id of ids) {
        const mark = marks[id] ?? null;
        if (ok) known.set(id, mark);
        (batch.get(id) ?? []).forEach((done) => done(mark));
      }
    }
  }

  return {
    get(id: string): Promise<ReplyMark | null> {
      if (known.has(id)) return Promise.resolve(known.get(id) ?? null);
      return new Promise((resolve) => {
        waiting.set(id, [...(waiting.get(id) ?? []), resolve]);
        if (!timer) timer = setTimeout(() => void flush(), delayMs);
      });
    },
    /** Keep the loader in step with what this person just did (saved or undone). */
    set(id: string, mark: ReplyMark | null) {
      known.set(id, mark);
    },
  };
}

export const replyMarks = createMarkLoader();
