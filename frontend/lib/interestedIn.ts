/** "Interested in": pick Catalogue items for one customer. Same cap as the server. */
export const MAX_INTERESTED_ITEMS = 10;

/** Tick or untick one item. Ticking past the cap changes nothing. */
export function toggleItem(ids: string[], id: string, max: number = MAX_INTERESTED_ITEMS): string[] {
  if (ids.includes(id)) return ids.filter((x) => x !== id);
  return ids.length >= max ? ids : [...ids, id];
}
