"use client";
import { useMemo, useState } from "react";
import { coursesApi, type Batch } from "@/lib/coursesApi";
import { BTN_PRIMARY, BTN_SECONDARY, Field, INPUT_CLS, Notice, Sheet, errorText } from "@/app/dashboard/bookings/bookingsUi";
import { dayText, partsProblem, rupees, splitParts } from "./coursesLogic";

function todayIso(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Enrol a student: contact, parent's number, and how the fee is paid (one go, or equal parts a month apart). */
export function EnrolSheet({ batch, onClose, onDone }: { batch: Batch; onClose: () => void; onDone: () => void }) {
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [parent, setParent] = useState("");
  const [count, setCount] = useState("1");
  const [first, setFirst] = useState(todayIso());
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const total = batch.fee_paise ?? 0;
  const n = Math.max(1, Math.min(parseInt(count, 10) || 1, 24));
  const parts = useMemo(() => splitParts(total, n, first || todayIso()), [total, n, first]);
  const problem = total > 0 ? partsProblem(parts, total) : null;

  async function save() {
    if (!phone.trim()) return setErr("Type the student's WhatsApp number");
    setBusy(true);
    setErr("");
    try {
      await coursesApi.enrol(batch.id, {
        phone: phone.trim(), name: name.trim() || undefined, parent_phone: parent.trim() || undefined,
        instalments: n, first_due_on: first || undefined,
      });
      onDone();
    } catch (e) {
      setErr(errorText(e, "Could not enrol this student."));
      setBusy(false);
    }
  }

  return (
    <Sheet title={`Enrol a student in ${batch.name}`} onClose={onClose} footer={
      <>
        <button type="button" className={BTN_SECONDARY} onClick={onClose} disabled={busy}>Cancel</button>
        <button type="button" className={BTN_PRIMARY} onClick={save} disabled={busy || total <= 0 || Boolean(problem)}>{busy ? "Enrolling…" : "Enrol"}</button>
      </>
    }>
      <div className="space-y-3">
        <Field label="Student name" htmlFor="e-name"><input id="e-name" className={INPUT_CLS} value={name} onChange={(e) => setName(e.target.value)} maxLength={120} /></Field>
        <Field label="Student's WhatsApp number" htmlFor="e-phone"><input id="e-phone" inputMode="tel" className={INPUT_CLS} value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="98765 43210" /></Field>
        <Field label="Parent's number (optional)" htmlFor="e-parent" hint="Only used for fee reminders.">
          <input id="e-parent" inputMode="tel" className={INPUT_CLS} value={parent} onChange={(e) => setParent(e.target.value)} />
        </Field>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Pay in how many parts" htmlFor="e-count"><input id="e-count" inputMode="numeric" className={INPUT_CLS} value={count} onChange={(e) => setCount(e.target.value)} /></Field>
          <Field label="First part due on" htmlFor="e-first"><input id="e-first" type="date" className={INPUT_CLS} value={first} onChange={(e) => setFirst(e.target.value)} /></Field>
        </div>
        {total > 0 ? (
          <ul className="rounded-lg bg-[#f8fafc] p-3 text-sm text-ink-secondary">
            {parts.map((p, i) => <li key={p.due_on}>Part {i + 1}: {rupees(p.amount_paise)}, due {dayText(p.due_on)}</li>)}
          </ul>
        ) : <Notice tone="amber">This batch has no fee yet. Set the batch fee first.</Notice>}
        {problem ? <Notice tone="red">{problem}</Notice> : null}
        {err ? <Notice tone="red">{err}</Notice> : null}
      </div>
    </Sheet>
  );
}
