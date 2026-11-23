import type { Batch, FeePart, PartBody, ReminderState } from "@/lib/coursesApi";

/** 500000 -> "₹5,000"; 500050 -> "₹5,000.50". */
export function rupees(paise: number | undefined | null): string {
  const p = Math.round(Number(paise) || 0);
  const whole = Math.floor(p / 100).toLocaleString("en-IN");
  return p % 100 === 0 ? `₹${whole}` : `₹${whole}.${String(p % 100).padStart(2, "0")}`;
}

/** What a person types ("5000", "5,000", "₹ 5000.5") -> paise, or null when it is not an amount. */
export function rupeesToPaise(text: string): number | null {
  const clean = text.replace(/[₹,\s]/g, "");
  if (!/^\d+(\.\d{1,2})?$/.test(clean)) return null;
  return Math.round(parseFloat(clean) * 100);
}

function addDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

/** Equal parts a month apart; leftover paise on the first part (same as the server). */
export function splitParts(totalPaise: number, count: number, firstDue: string, everyDays = 30): PartBody[] {
  const n = Math.max(1, Math.min(Math.floor(count) || 1, 24));
  const base = Math.floor(totalPaise / n);
  const extra = totalPaise - base * n;
  return Array.from({ length: n }, (_, i) => ({
    due_on: addDays(firstDue, everyDays * i),
    amount_paise: base + (i === 0 ? extra : 0),
  }));
}

/** Why these parts cannot be saved, in plain words, or null when they are fine. */
export function partsProblem(parts: PartBody[], totalPaise: number): string | null {
  if (parts.length < 1 || parts.length > 24) return "A fee plan has 1 to 24 parts";
  for (const p of parts) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(p.due_on)) return "Every part needs a due date";
    if (!(p.amount_paise > 0)) return "Every part must be more than ₹0";
  }
  const sum = parts.reduce((s, p) => s + p.amount_paise, 0);
  return sum === totalPaise ? null : `The parts add up to ${rupees(sum)} but the fee is ${rupees(totalPaise)}`;
}

export function seatsText(b: Pick<Batch, "status" | "seats_left" | "seats_total" | "seats_waiting">): string {
  if (b.status === "closed") return "Closed";
  if (b.status === "full") return "Full";
  const waiting = b.seats_waiting > 0 ? ` (${b.seats_waiting} yet to pay)` : "";
  return `${b.seats_left} of ${b.seats_total} seats left${waiting}`;
}

export function statusLabel(status: Batch["status"]): string {
  return status === "open" ? "Open" : status === "full" ? "Full" : "Closed";
}

const MODE_LABEL = { online: "Online", offline: "In person", both: "Online and in person" } as const;
export const modeLabel = (mode: Batch["mode"]): string => MODE_LABEL[mode] ?? "In person";

/** "28 Nov" / "28 Nov 2027" (other year). Empty for no date. */
export function dayText(iso: string | null | undefined, thisYear = new Date().getFullYear()): string {
  if (!iso || !/^\d{4}-\d{2}-\d{2}/.test(iso)) return "";
  const d = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  const base = `${d.getUTCDate()} ${d.toLocaleString("en-GB", { month: "short", timeZone: "UTC" })}`;
  return d.getUTCFullYear() === thisYear ? base : `${base} ${d.getUTCFullYear()}`;
}

export function partLabel(p: Pick<FeePart, "paid" | "late" | "due_on"> & { on_order?: boolean }): string {
  if (p.paid) return p.on_order ? "Paid on the order" : "Paid";
  return p.late ? `Late, was due ${dayText(p.due_on)}` : `Due ${dayText(p.due_on)}`;
}

/** One line for the fee reminders card. */
export function reminderHelp(state: ReminderState | undefined): string {
  if (!state) return "";
  if (state.enabled) return "On. Parents and students get a WhatsApp 3 days before, on the day and 3 days after a part is due.";
  if (state.template === "APPROVED") return "Off. Switch it on to remind about unpaid parts.";
  if (state.template === "PENDING") return "Off. WhatsApp is still checking the reminder message. You can switch it on once it is approved.";
  if (state.template === "REJECTED") return "Off. WhatsApp turned the message down. Send it again.";
  return "Off. First send the reminder message to WhatsApp for approval.";
}

/** After dropping a student: what to tell the owner when the order was NOT cancelled because money was paid. */
export function dropNotice(r: { order_cancelled: boolean; paid_paise: number }): string {
  if (r.order_cancelled || !(r.paid_paise > 0)) return "";
  return `Order kept: this student has paid ${rupees(r.paid_paise)}. Refund it from the order if needed.`;
}
