import { cn } from "@/lib/utils";

/**
 * A count riding on an icon's top-right corner, like a phone app badge. Place
 * it inside a `relative` wrapper around the icon. It is decorative: the row
 * says the number to screen readers itself (navCountLabel).
 *
 * `group` is the menu-heading version: it shows only while that menu's rows
 * are hidden (menu shut, or the sidebar folded), summing the counts inside.
 */
export function NavCount({ count, group = false, shown = true }: { count: number; group?: boolean; shown?: boolean }) {
  if (count <= 0) return null;
  return (
    // Keyed on the count so a new arrival remounts it and replays the pop.
    <span key={count} className={cn("nav-pip", group && "nav-pip-group", shown && "is-on")} aria-hidden="true">
      {count > 9 ? "9+" : count}
    </span>
  );
}

export const navCountLabel = (count: number) => (count > 0 ? `, ${count} waiting` : "");
