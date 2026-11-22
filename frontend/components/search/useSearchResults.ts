"use client";
import { useEffect, useState } from "react";
import { searchEverything } from "@/lib/searchApi";
import { DEBOUNCE_MS, buildSections, canSearch, type SearchSection } from "./searchLogic";

export type SearchStatus = "idle" | "loading" | "done" | "error";

export interface SearchState {
  status: SearchStatus;
  sections: SearchSection[];
  /** The trimmed query these sections answer. */
  forQuery: string;
}

const IDLE: SearchState = { status: "idle", sections: [], forQuery: "" };

/** Runs the search 250 ms after the person stops typing; an older answer never replaces a newer one. */
export function useSearchResults(query: string): SearchState {
  const [state, setState] = useState<SearchState>(IDLE);
  const q = query.trim();
  const ready = canSearch(q);

  useEffect(() => {
    if (!ready) return;
    let live = true;
    const timer = setTimeout(async () => {
      setState((s) => ({ ...s, status: "loading" }));
      try {
        const res = await searchEverything(q);
        if (live) {
          setState(res.busy
            ? { status: "error", sections: [], forQuery: q }
            : { status: "done", sections: buildSections(res.groups), forQuery: q });
        }
      } catch {
        if (live) setState({ status: "error", sections: [], forQuery: q });
      }
    }, DEBOUNCE_MS);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [q, ready]);

  return ready ? state : IDLE;
}
