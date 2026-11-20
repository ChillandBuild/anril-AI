import { chipSetFor, type NavAccess, type NavPage } from "./navSections";

export interface ChipRow {
  chips: readonly NavPage[];
  /** href of the chip for the page you are on. */
  activeHref: string | null;
}

/**
 * The chip row for this page, or null when there should be none: the page has
 * no sibling pages, or the user can open fewer than two of them (a row with one
 * chip is just the page title again).
 */
export function chipRowFor(pathname: string, access: NavAccess): ChipRow | null {
  const set = chipSetFor(pathname);
  if (!set) return null;
  const chips = set.chips.filter((chip) => chip.visible(access));
  if (chips.length < 2) return null;
  const active = chips.find((chip) => chip.isActive(pathname));
  return { chips, activeHref: active?.href ?? null };
}
