import type { TeachItem, TeachOffer } from "@/lib/api";

export const SOURCE_LABEL: Record<TeachItem["source"], string> = {
  manual: "added here",
  chat: "from Chats",
  couldnt_answer: "from Couldn't answer",
};

/** "Taught 3 times" only once it has been taught more than once. */
export function taughtLabel(times: number): string | null {
  return times > 1 ? `Taught ${times} times` : null;
}

export function filterItems(items: TeachItem[], query: string): TeachItem[] {
  const q = query.trim().toLowerCase();
  if (!q) return items;
  return items.filter((i) => i.prompt.toLowerCase().includes(q) || i.reply.toLowerCase().includes(q));
}

/** "2026-11-30" -> "30 Nov" (no timezone maths: the date is already an India calendar day). */
export function shortDate(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return iso;
  return `${d} ${["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][m - 1]}`;
}

export function offerLabel(o: Pick<TeachOffer, "status" | "starts_on" | "ends_on">): string {
  if (o.status === "live") return `Live · ends ${shortDate(o.ends_on)}`;
  if (o.status === "upcoming") return `Starts ${shortDate(o.starts_on)}`;
  return "Ended · AI stopped";
}

/** Today in India as YYYY-MM-DD, for the date pickers' min value. */
export function todayIst(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(now);
}

export function addDays(iso: string, days: number): string {
  const d = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

/** An example word and meaning that fits the kind of business; businessType is free text and may be empty. */
export function wordExample(businessType: string | null | undefined): { word: string; meaning: string } {
  const text = (businessType ?? "").toLowerCase();
  const has = (...words: string[]) => words.some((w) => text.includes(w));
  if (has("astro", "jothid", "jyotish", "service")) return { word: "jathagam", meaning: "birth chart" };
  if (has("real estate", "property", "builder")) return { word: "plot", meaning: "land" };
  if (has("education", "coaching", "school", "tuition", "institute", "training", "academy", "college")) return { word: "batch", meaning: "class group" };
  if (has("retail", "textile", "saree", "fashion", "boutique", "shop", "store", "jewel", "wholesale")) return { word: "pattu", meaning: "silk saree" };
  return { word: "COD", meaning: "cash on delivery" };
}
