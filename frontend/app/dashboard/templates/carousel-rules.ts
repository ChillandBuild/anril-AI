/** Meta's carousel rules that apply across cards (one card's own rules live in template-rules.ts). */

export type CarouselCardShape = {
  header_media_type: "IMAGE" | "VIDEO";
  header_media_url: string;
  body_text: string;
  buttons: { type: "QUICK_REPLY" | "URL"; text: string }[];
};

export const MIN_CARDS = 2;
export const MAX_CARDS = 10;

/** A card counts once it has its media link and its text. */
export function isComplete(c: CarouselCardShape): boolean {
  return !!c.header_media_url.trim() && !!c.body_text.trim();
}

/** The button pattern Meta compares between cards: the types, in order (texts may differ). */
export function buttonPattern(c: CarouselCardShape): string {
  return c.buttons.filter((b) => b.text.trim()).map((b) => b.type).join("+");
}

/** Meta rejects a carousel unless every card has the same media type and the same buttons. */
export function shapeProblems(cards: CarouselCardShape[]): { media: boolean; buttons: boolean } {
  const done = cards.filter(isComplete);
  return {
    media: new Set(done.map((c) => c.header_media_type)).size > 1,
    buttons: new Set(done.map(buttonPattern)).size > 1,
  };
}

/** The card list with card i moved one place left (-1) or right (+1). */
export function moveCard<T>(cards: T[], i: number, dir: -1 | 1): T[] {
  const j = i + dir;
  if (j < 0 || j >= cards.length) return cards;
  const next = [...cards];
  [next[i], next[j]] = [next[j], next[i]];
  return next;
}
