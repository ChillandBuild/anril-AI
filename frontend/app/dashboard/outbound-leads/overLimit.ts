// Helpers for the Confirm-step list of people who already got this week's broadcasts.

export type OverLimitPerson = { phone: string; name: string | null; this_week: number };

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function dayLabel(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  const date = new Date(Date.UTC(y, m - 1, d));
  return `${DAYS[date.getUTCDay()]} ${d} ${MONTHS[m - 1]}`;
}

/** "2026-11-15", "2026-11-21" -> "Sun 15 Nov – Sat 21 Nov" */
export function weekRangeLabel(start: string, end: string): string {
  return `${dayLabel(start)} – ${dayLabel(end)}`;
}

/** Case-insensitive on name; digits-only on phone (spaces and "+" in the query are ignored). */
export function matchPeople(people: OverLimitPerson[], query: string): OverLimitPerson[] {
  const q = query.trim().toLowerCase();
  if (!q) return people;
  const digits = q.replace(/\D/g, "");
  return people.filter(
    (p) => (p.name ?? "").toLowerCase().includes(q) || (digits !== "" && p.phone.replace(/\D/g, "").includes(digits)),
  );
}

/** Adds (on) or removes (off) every phone in `shown`; picks outside `shown` are left alone. */
export function toggleAll(picked: Set<string>, shown: OverLimitPerson[], on: boolean): Set<string> {
  const next = new Set(picked);
  for (const p of shown) {
    if (on) next.add(p.phone);
    else next.delete(p.phone);
  }
  return next;
}

/** Drops picks that are no longer in the list (after a re-preview). */
export function keepKnown(picked: Set<string>, people: OverLimitPerson[]): Set<string> {
  const known = new Set(people.map((p) => p.phone));
  return new Set(Array.from(picked).filter((ph) => known.has(ph)));
}
