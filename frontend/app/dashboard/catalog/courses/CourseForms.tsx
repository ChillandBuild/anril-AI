"use client";
import { useState } from "react";
import { coursesApi, type Batch, type BatchBody, type BatchMode, type Course } from "@/lib/coursesApi";
import { BTN_PRIMARY, BTN_SECONDARY, Field, INPUT_CLS, Notice, Sheet, errorText } from "@/app/dashboard/bookings/bookingsUi";
import { rupees, rupeesToPaise } from "./coursesLogic";

/** Add or rename a course. */
export function CourseSheet({ course, canMoney, onClose, onSaved }: {
  course: Course | null; canMoney: boolean; onClose: () => void; onSaved: () => void;
}) {
  const [name, setName] = useState(course?.name ?? "");
  const [desc, setDesc] = useState(course?.description ?? "");
  const [price, setPrice] = useState(course?.price_paise ? String(course.price_paise / 100) : "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function save() {
    const paise = price.trim() ? rupeesToPaise(price) : undefined;
    if (!name.trim()) return setErr("Give the course a name");
    if (paise === null) return setErr("Type the fee as a number, like 15000");
    setBusy(true);
    setErr("");
    try {
      const body = { name: name.trim(), description: desc.trim(), ...(canMoney && paise !== undefined ? { price_paise: paise } : {}) };
      if (course) await coursesApi.updateCourse(course.id, body);
      else await coursesApi.createCourse(body);
      onSaved();
    } catch (e) {
      setErr(errorText(e));
      setBusy(false);
    }
  }

  return (
    <Sheet title={course ? "Edit course" : "Add a course"} onClose={onClose} footer={
      <>
        <button type="button" className={BTN_SECONDARY} onClick={onClose} disabled={busy}>Cancel</button>
        <button type="button" className={BTN_PRIMARY} onClick={save} disabled={busy}>{busy ? "Saving…" : "Save"}</button>
      </>
    }>
      <div className="space-y-3">
        <Field label="Course name" htmlFor="course-name">
          <input id="course-name" className={INPUT_CLS} value={name} onChange={(e) => setName(e.target.value)} placeholder="Python for beginners" maxLength={120} />
        </Field>
        <Field label="What students learn (the AI shares this with parents)" htmlFor="course-desc">
          <textarea id="course-desc" className={`${INPUT_CLS} h-24 py-2`} value={desc} onChange={(e) => setDesc(e.target.value)} maxLength={2000} />
        </Field>
        {canMoney ? (
          <Field label="Course fee in rupees" htmlFor="course-fee" hint="Each batch can set its own fee too.">
            <input id="course-fee" className={INPUT_CLS} inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} placeholder="15000" />
          </Field>
        ) : null}
        {err ? <Notice tone="red">{err}</Notice> : null}
      </div>
    </Sheet>
  );
}

const MODES: { id: BatchMode; label: string }[] = [
  { id: "offline", label: "In person" },
  { id: "online", label: "Online" },
  { id: "both", label: "Online and in person" },
];

/** Add or edit a batch of one course. */
export function BatchSheet({ course, batch, canMoney, onClose, onSaved }: {
  course: Course; batch: Batch | null; canMoney: boolean; onClose: () => void; onSaved: () => void;
}) {
  const [name, setName] = useState(batch?.name ?? "");
  const [startsOn, setStartsOn] = useState(batch?.starts_on ?? "");
  const [timing, setTiming] = useState(batch?.timing_text ?? "");
  const [mode, setMode] = useState<BatchMode>(batch?.mode ?? "offline");
  const [seats, setSeats] = useState(String(batch?.seats_total ?? 20));
  const [fee, setFee] = useState(batch?.fee_paise !== undefined ? String(batch.fee_paise / 100) : course.price_paise ? String(course.price_paise / 100) : "");
  const [teacher, setTeacher] = useState(batch?.teacher_name ?? "");
  const [full, setFull] = useState(batch?.stored_status === "full");
  const [closed, setClosed] = useState(batch?.stored_status === "closed");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function save() {
    const n = parseInt(seats, 10);
    const paise = fee.trim() ? rupeesToPaise(fee) : undefined;
    if (!name.trim()) return setErr("Give the batch a name, like Morning batch");
    if (!(n >= 0)) return setErr("Seats must be a number");
    if (paise === null) return setErr("Type the fee as a number, like 15000");
    const body: BatchBody = {
      name: name.trim(), starts_on: startsOn || null, timing_text: timing.trim() || null, mode,
      seats_total: n, teacher_name: teacher.trim() || null, status: closed ? "closed" : full ? "full" : "open",
      ...(canMoney && paise !== undefined ? { fee_paise: paise } : {}),
    };
    setBusy(true);
    setErr("");
    try {
      if (batch) await coursesApi.updateBatch(batch.id, body);
      else await coursesApi.createBatch(course.id, body);
      onSaved();
    } catch (e) {
      setErr(errorText(e));
      setBusy(false);
    }
  }

  return (
    <Sheet title={batch ? `Edit ${batch.name}` : `New batch of ${course.name}`} onClose={onClose} footer={
      <>
        <button type="button" className={BTN_SECONDARY} onClick={onClose} disabled={busy}>Cancel</button>
        <button type="button" className={BTN_PRIMARY} onClick={save} disabled={busy}>{busy ? "Saving…" : "Save"}</button>
      </>
    }>
      <div className="space-y-3">
        <Field label="Batch name" htmlFor="b-name">
          <input id="b-name" className={INPUT_CLS} value={name} onChange={(e) => setName(e.target.value)} placeholder="Morning batch" maxLength={120} />
        </Field>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Starts on" htmlFor="b-start"><input id="b-start" type="date" className={INPUT_CLS} value={startsOn} onChange={(e) => setStartsOn(e.target.value)} /></Field>
          <Field label="Seats" htmlFor="b-seats"><input id="b-seats" inputMode="numeric" className={INPUT_CLS} value={seats} onChange={(e) => setSeats(e.target.value)} /></Field>
        </div>
        <Field label="Timing" htmlFor="b-timing"><input id="b-timing" className={INPUT_CLS} value={timing} onChange={(e) => setTiming(e.target.value)} placeholder="Mon to Fri, 7 to 8 am" maxLength={200} /></Field>
        <Field label="How it is taught" htmlFor="b-mode">
          <select id="b-mode" className={INPUT_CLS} value={mode} onChange={(e) => setMode(e.target.value as BatchMode)}>
            {MODES.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
          </select>
        </Field>
        <Field label="Teacher" htmlFor="b-teacher"><input id="b-teacher" className={INPUT_CLS} value={teacher} onChange={(e) => setTeacher(e.target.value)} maxLength={120} /></Field>
        {canMoney ? (
          <Field label="Batch fee in rupees" htmlFor="b-fee" hint={batch?.fee_paise ? `Now ${rupees(batch.fee_paise)}. A new fee is not applied to students already enrolled.` : undefined}>
            <input id="b-fee" className={INPUT_CLS} inputMode="decimal" value={fee} onChange={(e) => setFee(e.target.value)} placeholder="15000" />
          </Field>
        ) : null}
        <label className="flex items-center gap-2 text-sm text-ink"><input type="checkbox" checked={full} onChange={(e) => setFull(e.target.checked)} /> Mark as full (stop taking students)</label>
        <label className="flex items-center gap-2 text-sm text-ink"><input type="checkbox" checked={closed} onChange={(e) => setClosed(e.target.checked)} /> Close this batch (hide it from parents)</label>
        {err ? <Notice tone="red">{err}</Notice> : null}
      </div>
    </Sheet>
  );
}
