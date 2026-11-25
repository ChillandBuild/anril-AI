import type { AlertRow, QuietTime, WhoChoice } from "@/lib/automationsApi";

export type AlertEdit = { on: boolean; who: WhoChoice[] };
export type QuietEdit = { on: boolean; start: number; end: number };

export type AlertChange = { key: string; on: boolean; who?: WhoChoice[] };

function sameWho(a: WhoChoice[], b: WhoChoice[]): boolean {
  return a.length === b.length && a.every((x) => b.includes(x));
}

/** The alerts whose draft differs from what is saved. `who` is only included when the people changed. */
export function changedAlerts(rows: AlertRow[], edits: Record<string, AlertEdit>): AlertChange[] {
  const out: AlertChange[] = [];
  for (const r of rows) {
    const e = edits[r.key];
    if (!e) continue;
    const whoChanged = !sameWho(e.who, r.who);
    if (e.on === r.on && !whoChanged) continue;
    out.push(whoChanged ? { key: r.key, on: e.on, who: e.who } : { key: r.key, on: e.on });
  }
  return out;
}

export function quietChanged(saved: QuietTime, edit: QuietEdit | null): boolean {
  if (!edit) return false;
  return edit.on !== saved.on || edit.start !== saved.start_hour || edit.end !== saved.end_hour;
}
