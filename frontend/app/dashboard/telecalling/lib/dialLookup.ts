import { apiFetch } from "@/lib/api";

export interface DialMatch {
  id: string;
  name: string | null;
  /** Masked (98•••••210) when the business hides numbers from telecallers. */
  phone: string | null;
  segment: "A" | "B" | "C" | "D" | null;
  is_buyer: boolean;
  phone_hidden: boolean;
}

/** Digits (and + - space) search the number; anything with a letter searches the name. */
export function isNumberEntry(text: string): boolean {
  return /^[\d\s+\-*#()]+$/.test(text.trim());
}

/** Worth asking the server: 3+ digits for a number, 2+ letters for a name. */
export function worthLooking(text: string): boolean {
  const t = text.trim();
  if (!t) return false;
  return isNumberEntry(t) ? t.replace(/\D/g, "").length >= 3 : t.length >= 2;
}

export function lookupCustomers(text: string): Promise<{ matches: DialMatch[] }> {
  return apiFetch<{ matches: DialMatch[] }>(`/api/v1/dial/lookup?q=${encodeURIComponent(text.trim())}`);
}

export const SEGMENT_WORD: Record<string, string> = { A: "Hot", B: "Warm", C: "Cold", D: "Not interested" };
