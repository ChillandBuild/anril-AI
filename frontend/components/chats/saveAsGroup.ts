/** Chats > Filter > "Save as a group": the helper behind the dialog. The server collects every
 *  chat the current tab, search and filters match (not just the loaded page) and saves them as a
 *  fixed Customers > Groups group: POST /api/v1/customer-groups/from-chats. */
import { API_URL, getAuthHeaders } from "@/lib/api";
import { filterParams, type InboxChannel, type InboxFilters, type ListView } from "./inboxFilters";

/** The most people one saved group can hold (the server enforces the same number). */
export const MAX_GROUP_PEOPLE = 5000;

export interface SavedChatsGroup {
  id: string;
  name: string;
  /** How many people were put in the group. */
  added: number;
}

/** The request body: the same words the Chats list sends as its query string. */
export function fromChatsBody(
  name: string,
  f: InboxFilters,
  opts: { view: ListView; channel: InboxChannel; search?: string },
): Record<string, string> {
  return { name: name.trim(), ...Object.fromEntries(filterParams(f, opts)) };
}

export async function saveChatsAsGroup(body: Record<string, string>): Promise<SavedChatsGroup> {
  const auth = await getAuthHeaders();
  const res = await fetch(`${API_URL}/api/v1/customer-groups/from-chats`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...auth },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof data?.detail === "string" ? data.detail : null;
    throw new Error(detail ?? "Couldn't save the group. Try again.");
  }
  return { id: data.id, name: data.name, added: data.added ?? data.member_count ?? 0 };
}

/** The success toast: Saved 14 people to “Insta Hot – Nov”. */
export function savedGroupMessage(added: number, name: string): string {
  return `Saved ${added.toLocaleString("en-IN")} ${added === 1 ? "person" : "people"} to “${name}”`;
}

/** Where the toast's link goes: Customers > Groups. */
export const GROUPS_PAGE = "/dashboard/leads?tab=groups";
