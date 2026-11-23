"use client";
import { useState } from "react";
import useSWR from "swr";
import { coursesApi, type Batch, type Course } from "@/lib/coursesApi";
import { BTN_DANGER, BTN_PRIMARY, BTN_SECONDARY, ConfirmSheet, Field, INPUT_CLS, Notice, Sheet, errorText } from "@/app/dashboard/bookings/bookingsUi";
import { EnrolSheet } from "./EnrolSheet";
import { FeePlanView } from "./FeePlanView";
import { dayText, dropNotice, modeLabel, seatTemplateHelp, seatsText, waitlistNote } from "./coursesLogic";

/** One batch: its students (with fee parts), the waitlist, and the buttons to enrol, edit or drop. */
export function BatchPanel({ course, batchId, canManage, canMoney, canDeals, onClose, onEdit }: {
  course: Course; batchId: string; canManage: boolean; canMoney: boolean; canDeals: boolean;
  onClose: () => void; onEdit: (b: Batch) => void;
}) {
  const { data, error, mutate } = useSWR(["courses/batch", batchId], () => coursesApi.batch(batchId), { revalidateOnFocus: false });
  const [enrol, setEnrol] = useState(false);
  const [dropId, setDropId] = useState<string | null>(null);
  const [wName, setWName] = useState("");
  const [wPhone, setWPhone] = useState("");
  const [err, setErr] = useState("");
  const [kept, setKept] = useState("");
  const [busy, setBusy] = useState(false);

  const batch = data?.batch;
  async function run(job: () => Promise<unknown>, failure: string) {
    setBusy(true);
    setErr("");
    try {
      await job();
      await mutate();
    } catch (e) {
      setErr(errorText(e, failure));
    } finally {
      setBusy(false);
    }
  }
  async function addWaiting() {
    if (!wPhone.trim()) return setErr("Type the WhatsApp number to put on the waiting list");
    await run(async () => {
      await coursesApi.joinWaitlist(batchId, { phone: wPhone.trim(), name: wName.trim() || undefined });
      setWName("");
      setWPhone("");
    }, "Could not add to the waiting list.");
  }

  return (
    <Sheet wide title={`${course.name}: ${batch?.name ?? "Batch"}`} onClose={onClose} footer={
      <>
        {canManage && batch ? <button type="button" className={BTN_SECONDARY} onClick={() => onEdit(batch)}>Edit batch</button> : null}
        {canDeals && batch && batch.status === "open" ? <button type="button" className={BTN_PRIMARY} onClick={() => setEnrol(true)}>Enrol a student</button> : null}
      </>
    }>
      {error ? <Notice tone="red">{errorText(error, "Could not load this batch.")}</Notice> : null}
      {!data && !error ? <div className="h-32 animate-pulse rounded-xl bg-surface-low" /> : null}
      {batch ? (
        <div className="space-y-4">
          <p className="text-sm text-ink-secondary">
            {[batch.starts_on ? `Starts ${dayText(batch.starts_on)}` : "", batch.timing_text ?? "", modeLabel(batch.mode), batch.teacher_name ?? ""].filter(Boolean).join(" · ")}
            <br />{seatsText(batch)}
          </p>
          {batch.status !== "open" && data?.next_open_batch ? <Notice>The next batch with seats is {data.next_open_batch.name}.</Notice> : null}
          {err ? <Notice tone="red">{err}</Notice> : null}
          {kept ? <Notice tone="amber">{kept}</Notice> : null}

          <section aria-label="Students">
            <h3 className="mb-1 text-sm font-bold text-ink">Students ({data.students.length})</h3>
            {data.students.length === 0 ? <p className="text-sm text-ink-secondary">No students yet.</p> : null}
            <ul className="space-y-3">
              {data.students.map((s) => (
                <li key={s.id} className="rounded-xl border border-[#e2e8f0] p-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-bold text-ink">{s.name || s.phone}</p>
                      <p className="text-sm text-ink-secondary">{s.phone}{s.parent_phone ? ` · Parent ${s.parent_phone}` : ""}{s.paid ? "" : " · Nothing paid yet"}</p>
                    </div>
                    {canDeals ? <button type="button" className={BTN_DANGER} onClick={() => setDropId(s.id)}>Drop</button> : null}
                  </div>
                  {canMoney && s.fee_plan ? <FeePlanView plan={s.fee_plan} canPay={canDeals} onChanged={() => void mutate()} /> : null}
                </li>
              ))}
            </ul>
          </section>

          <section aria-label="Waiting list">
            <h3 className="mb-1 text-sm font-bold text-ink">Waiting list ({data.waitlist.length})</h3>
            <ul className="space-y-1">
              {data.waitlist.map((w) => (
                <li key={w.id} className="flex items-center justify-between gap-2 text-sm text-ink">
                  <span className="min-w-0">
                    <span className="block truncate">{w.name ? `${w.name} · ` : ""}{w.phone}</span>
                    {waitlistNote(w) ? <span className={`block text-xs ${w.told_via === "staff" ? "font-semibold text-amber-800" : "text-ink-secondary"}`}>{waitlistNote(w)}</span> : null}
                  </span>
                  {canManage ? <button type="button" className={BTN_SECONDARY} disabled={busy} onClick={() => run(() => coursesApi.leaveWaitlist(w.id), "Could not remove that.")}>Remove</button> : null}
                </li>
              ))}
            </ul>
            {data.waitlist.length > 0 || batch.status !== "open" ? (() => {
              const help = seatTemplateHelp(data.seat_template);
              return (
                <p className="mt-2 text-xs text-ink-secondary">
                  {help.text}{" "}
                  {canManage && help.canSend ? (
                    <button type="button" className="font-semibold text-primary underline" disabled={busy}
                      onClick={() => run(() => coursesApi.submitSeatTemplate(), "Could not send the message to WhatsApp.")}>
                      Send the seat message for approval
                    </button>
                  ) : null}
                </p>
              );
            })() : null}
            {canManage ? (
              <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-[1fr_1fr_auto]">
                <Field label="Name" htmlFor="w-name"><input id="w-name" className={INPUT_CLS} value={wName} onChange={(e) => setWName(e.target.value)} /></Field>
                <Field label="WhatsApp number" htmlFor="w-phone"><input id="w-phone" inputMode="tel" className={INPUT_CLS} value={wPhone} onChange={(e) => setWPhone(e.target.value)} /></Field>
                <div className="flex items-end"><button type="button" className={BTN_SECONDARY} disabled={busy} onClick={addWaiting}>Add</button></div>
              </div>
            ) : null}
          </section>
        </div>
      ) : null}

      {enrol && batch ? <EnrolSheet batch={batch} onClose={() => setEnrol(false)} onDone={() => { setEnrol(false); void mutate(); }} /> : null}
      {dropId ? (
        <ConfirmSheet title="Drop this student?" body="The seat is freed and an unpaid order is cancelled. Money already paid stays on record. If someone is on the waiting list, the first person is told the seat is free."
          confirmLabel="Drop student" tone="danger" busy={busy} onClose={() => setDropId(null)}
          onConfirm={() => {
            const id = dropId;
            setDropId(null);
            setKept("");
            void run(async () => setKept(dropNotice(await coursesApi.drop(id))), "Could not drop this student.");
          }} />
      ) : null}
    </Sheet>
  );
}
