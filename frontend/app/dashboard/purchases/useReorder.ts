"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { ReorderSuggestion } from "@/lib/api";

/** The reorder suggestions, read once (they fill a new purchase order). */
export function useReorderSuggestionsOnce(enabled: boolean) {
  const [data, setData] = useState<ReorderSuggestion[]>([]);
  const [loading, setLoading] = useState(enabled);
  useEffect(() => {
    if (!enabled) return;
    api.purchases.suggestions().then((r) => setData(r.data)).catch(() => setData([])).finally(() => setLoading(false));
  }, [enabled]);
  return { data, loading };
}
