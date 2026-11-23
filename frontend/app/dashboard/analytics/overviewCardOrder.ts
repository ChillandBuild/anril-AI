// Which Overview cards come first for which kind of business. The backend sends the cards in one
// fixed order; this only re-sorts what it sent (it never adds or drops a card). No React here, so
// it is unit-tested.

export type OverviewKind = "service" | "shop" | "leads";

/** The business type is free text ("Healthcare", "Real Estate", "Salon & spa"); null when it is not recognised. */
export function overviewKind(businessType: string | null | undefined): OverviewKind | null {
  const text = (businessType ?? "").toLowerCase().replace(/[^a-z]+/g, " ").trim();
  if (!text) return null;
  const has = (...words: string[]) => words.some((word) => text.includes(word));
  if (has("real estate", "realestate", "property", "builder", "education", "coaching", "school", "tuition", "institute", "training", "academy", "college")) {
    return "leads";
  }
  if (has("clinic", "health", "hospital", "dental", "dentist", "doctor", "salon", "spa", "beauty", "fitness", "gym", "physio", "diagnostic", "wellness", "service")) {
    return "service";
  }
  if (has("shop", "retail", "store", "grocery", "commerce", "restaurant", "food", "bakery", "fashion", "boutique", "jewel", "wholesale")) {
    return "shop";
  }
  return null;
}

/** Card keys shown first, in order. Any other card follows in the order the backend sent it. */
const FIRST: Record<OverviewKind, string[]> = {
  service: ["bookings", "first_chats", "paid", "sales_paise"],
  shop: ["sales_paise", "paid", "new_buyers", "first_chats"],
  leads: ["first_chats", "hot", "bookings", "paid"],
};

/** Same cards, nothing dropped, put in the order that suits the business. Unknown type keeps the backend order. */
export function orderOverviewCards<T extends { key: string }>(cards: T[], businessType: string | null | undefined): T[] {
  const kind = overviewKind(businessType);
  if (!kind) return cards;
  const rank = (card: T) => {
    const at = FIRST[kind].indexOf(card.key);
    return at === -1 ? FIRST[kind].length : at;
  };
  // Array.prototype.sort is stable, so cards that share a rank keep the backend's order.
  return [...cards].sort((a, b) => rank(a) - rank(b));
}
