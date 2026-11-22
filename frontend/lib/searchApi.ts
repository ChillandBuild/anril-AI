import { apiFetch } from "@/lib/api";

/** One answer group from GET /api/v1/search. Items differ a little per group (see searchLogic.buildSections). */
export interface SearchGroupApi {
  key: string;
  title: string;
  items: Record<string, unknown>[];
}

export interface SearchResponse {
  query: string;
  groups: SearchGroupApi[];
  /** True when the person already has searches running; the answer is empty, not "no matches". */
  busy?: boolean;
}

/** The box in the top bar. Groups the person may not see are simply missing from the answer. */
export function searchEverything(q: string): Promise<SearchResponse> {
  return apiFetch<SearchResponse>(`/api/v1/search?q=${encodeURIComponent(q.trim())}`);
}
