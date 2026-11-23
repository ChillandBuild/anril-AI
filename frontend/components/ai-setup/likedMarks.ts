import { api } from "@/lib/api";

/** Whether this person saved an AI reply as a style example ("Replies you like"), per message id. */
export type LikedFetcher = (ids: string[]) => Promise<string[]>;

const MAX_IDS_PER_CALL = 100;

export function chunkIds(ids: string[], size = MAX_IDS_PER_CALL): string[][] {
  const out: string[][] = [];
  for (let i = 0; i < ids.length; i += size) out.push(ids.slice(i, i + size));
  return out;
}

const fetchLiked: LikedFetcher = async (ids) => {
  const res = await api.aiTeach.likedMarks(ids);
  return res?.liked ?? [];
};

/**
 * Asks for the liked state of every AI reply on screen in one call: each reply asks for its own id, the asks made in
 * the same moment are sent together. Answers are remembered. If the call fails, those replies count as not liked and
 * are not asked for again in a loop.
 */
export function createLikedLoader(fetcher: LikedFetcher = fetchLiked, delayMs = 40) {
  const known = new Map<string, boolean>();
  const waiting = new Map<string, Array<(liked: boolean) => void>>();
  let timer: ReturnType<typeof setTimeout> | null = null;

  async function flush() {
    timer = null;
    const batch = new Map(waiting);
    waiting.clear();
    for (const ids of chunkIds(Array.from(batch.keys()))) {
      let likedIds: string[] = [];
      try {
        likedIds = await fetcher(ids);
      } catch {
        likedIds = []; // treated as not liked, and remembered so it does not retry in a loop
      }
      const liked = new Set(likedIds);
      for (const id of ids) {
        const value = liked.has(id);
        known.set(id, value);
        (batch.get(id) ?? []).forEach((done) => done(value));
      }
    }
  }

  return {
    get(id: string): Promise<boolean> {
      if (known.has(id)) return Promise.resolve(known.get(id) ?? false);
      return new Promise((resolve) => {
        waiting.set(id, [...(waiting.get(id) ?? []), resolve]);
        if (!timer) timer = setTimeout(() => void flush(), delayMs);
      });
    },
    /** Keep the loader in step with what this person just did (liked or undone). */
    set(id: string, liked: boolean) {
      known.set(id, liked);
    },
  };
}

export const likedMarks = createLikedLoader();
