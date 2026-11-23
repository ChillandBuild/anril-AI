"use client";
import { useState } from "react";
import Link from "next/link";
import { Plus } from "lucide-react";
import { toast } from "sonner";
import { Select } from "@/components/ui/Select";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { SwitchPill } from "@/components/ui/controls";
import { ROLES_HREF } from "@/components/settingsNavigation";
import { bookingsApi, type BookingResource, type BookingSetup, type ResourceBody, type ResourceKind } from "@/lib/bookingsApi";
import { defaultHours, hoursSummary, normaliseHours, validateHours } from "./bookingsLogic";
import { DAY_SHORT, addDays, formatDay, todayIst, weekdayIndex } from "./bookingsTime";
import { HoursEditor } from "./HoursEditor";
import { BTN_DANGER, BTN_PRIMARY, BTN_SECONDARY, ConfirmSheet, Field, INPUT_CLS, Notice, Sheet, errorText } from "./bookingsUi";

/** A linked person whose role cannot open Bookings sees nothing until the role gets "View bookings". */
function NoViewNotice({ name }: { name: string }) {
  return (
    <Notice tone="amber">
      {name} can&apos;t see bookings yet. Give their role &quot;View bookings&quot; in{" "}
      <Link href={ROLES_HREF} className="font-bold underline">
        Team &amp; roles
      </Link>
      .
    </Notice>
  );
}

const KIND_LABEL: Record<ResourceKind, string> = { person: "Person", chair: "Chair", room: "Room" };

/** One card per staff member / chair: name, who is linked, hours, services, leave. */
export function StaffTab({ setup, canManage, onChanged }: { setup: BookingSetup; canManage: boolean; onChanged: () => void }) {
  const [editing, setEditing] = useState<BookingResource | "new" | null>(null);
  // The server already limits this list to what the person may see.
  const resources = setup.resources;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="font-display text-lg font-bold text-ink">By staff / chair</h2>
        {canManage && (
          <button type="button" className={BTN_PRIMARY} onClick={() => setEditing("new")}>
            <Plus size={16} aria-hidden /> Add staff / chair
          </button>
        )}
      </div>
      {resources.length === 0 && <Notice>{canManage ? "No staff or chairs yet. Add one to start taking bookings." : "Nothing to show here."}</Notice>}
      <ul className="grid gap-3 lg:grid-cols-2">
        {resources.map((r) => (
          <ResourceCard key={r.id} r={r} setup={setup} canManage={canManage} onEdit={() => setEditing(r)} onChanged={onChanged} />
        ))}
      </ul>
      {editing && (
        <ResourceEditor
          key={editing === "new" ? "new" : editing.id}
          existing={editing === "new" ? null : editing}
          setup={setup}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            onChanged();
          }}
        />
      )}
    </div>
  );
}

function ResourceCard({ r, setup, canManage, onEdit, onChanged }: { r: BookingResource; setup: BookingSetup; canManage: boolean; onEdit: () => void; onChanged: () => void }) {
  const member = r.user_id ? setup.team.find((t) => t.user_id === r.user_id) : undefined;
  const person = member?.name ?? null;
  const services = setup.services.filter((s) => r.service_ids.includes(s.id));
  const leave = setup.leave.filter((l) => l.resource_id === r.id);
  const [leaving, setLeaving] = useState(false);
  const todayDay = weekdayIndex(todayIst());

  return (
    <li className="min-w-0 rounded-2xl border border-[#e8edf2] bg-white p-4 shadow-sm">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate font-display text-base font-bold text-ink">{r.name}</h3>
          <p className="text-sm text-ink-muted">
            {KIND_LABEL[r.kind]}
            {person ? ` · ${person}` : ""}
            {!r.active ? " · Not taking bookings" : ""}
          </p>
          {member && member.has_view === false && (
            <div className="mt-2">
              <NoViewNotice name={member.name} />
            </div>
          )}
        </div>
        {canManage && (
          <button type="button" className={BTN_SECONDARY} onClick={onEdit}>
            Edit
          </button>
        )}
      </div>
      <dl className="mt-3 space-y-1.5 text-sm">
        <div className="flex gap-2">
          <dt className="w-20 shrink-0 text-ink-muted">Today</dt>
          <dd className="text-ink">{hoursSummary(normaliseHours(r.hours)[String(todayDay)])}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="w-20 shrink-0 text-ink-muted">Does</dt>
          <dd className="min-w-0 text-ink">{services.length ? services.map((s) => s.name).join(", ") : "No services picked"}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="w-20 shrink-0 text-ink-muted">Days off</dt>
          <dd className="min-w-0 text-ink">
            {leave.length === 0 ? (
              "None coming up"
            ) : (
              <ul className="space-y-1">
                {leave.map((l) => (
                  <li key={l.id} className="flex items-center gap-2">
                    <span>
                      {l.from_date === l.to_date ? formatDay(l.from_date) : `${formatDay(l.from_date)} – ${formatDay(l.to_date)}`}
                      {l.note ? ` · ${l.note}` : ""}
                    </span>
                    {canManage && (
                      <button
                        type="button"
                        className="text-xs font-bold text-rose-700 hover:underline"
                        aria-label={`Remove leave ${formatDay(l.from_date)}`}
                        onClick={async () => {
                          try {
                            await bookingsApi.removeLeave(l.id);
                            onChanged();
                          } catch (err) {
                            toast.error(errorText(err));
                          }
                        }}
                      >
                        Remove
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </dd>
        </div>
      </dl>
      {canManage && (
        <button type="button" className="mt-3 text-sm font-bold text-primary-700 hover:underline" onClick={() => setLeaving(true)}>
          Mark leave
        </button>
      )}
      {leaving && <LeaveSheet r={r} onClose={() => setLeaving(false)} onSaved={() => { setLeaving(false); onChanged(); }} />}
    </li>
  );
}

function LeaveSheet({ r, onClose, onSaved }: { r: BookingResource; onClose: () => void; onSaved: () => void }) {
  const today = todayIst();
  const [from, setFrom] = useState(today);
  const [to, setTo] = useState(today);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const bad = !from || !to || to < from;

  async function save() {
    setBusy(true);
    try {
      await bookingsApi.addLeave(r.id, { from_date: from, to_date: to, note: note.trim() || undefined });
      toast.success("Leave saved");
      onSaved();
    } catch (err) {
      toast.error(errorText(err));
      setBusy(false);
    }
  }

  return (
    <Sheet
      title={`Mark leave for ${r.name}`}
      onClose={onClose}
      labelId="leave-title"
      footer={
        <>
          <button type="button" className={BTN_SECONDARY} onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="button" className={BTN_PRIMARY} onClick={() => void save()} disabled={busy || bad}>
            Save leave
          </button>
        </>
      }
    >
      <div className="space-y-3">
        <p className="text-sm text-ink-secondary">No new bookings can be made on these days. Bookings already made stay as they are.</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="From" htmlFor="leave-from">
            <input id="leave-from" type="date" min={today} value={from} onChange={(e) => { setFrom(e.target.value); if (to < e.target.value) setTo(e.target.value); }} className={INPUT_CLS} />
          </Field>
          <Field label="To (last day off)" htmlFor="leave-to">
            <input id="leave-to" type="date" min={from || addDays(today, 0)} value={to} onChange={(e) => setTo(e.target.value)} className={INPUT_CLS} />
          </Field>
        </div>
        <Field label="Note (optional)" htmlFor="leave-note">
          <input id="leave-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={200} className={INPUT_CLS} />
        </Field>
        {to < from && <Notice tone="red">The last day must not be before the first day.</Notice>}
      </div>
    </Sheet>
  );
}

function ResourceEditor({ existing, setup, onClose, onSaved }: { existing: BookingResource | null; setup: BookingSetup; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(existing?.name ?? "");
  const [kind, setKind] = useState<ResourceKind>(existing?.kind ?? "person");
  const [userId, setUserId] = useState(existing?.user_id ?? "");
  const [active, setActive] = useState(existing?.active ?? true);
  const [hours, setHours] = useState(() => normaliseHours(existing?.hours ?? defaultHours()));
  const [serviceIds, setServiceIds] = useState<string[]>(existing?.service_ids ?? setup.services.filter((s) => s.active).map((s) => s.id));
  const [busy, setBusy] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const hoursErrors = validateHours(hours);
  const canSave = name.trim().length > 0 && Object.keys(hoursErrors).length === 0 && !busy;

  // One login can be linked to one column only.
  const takenUsers = new Set(setup.resources.filter((r) => r.id !== existing?.id && r.user_id).map((r) => r.user_id as string));
  const people = setup.team.filter((t) => !takenUsers.has(t.user_id));
  const pickedMember = userId ? setup.team.find((t) => t.user_id === userId) : undefined;

  async function save() {
    setBusy(true);
    const body: ResourceBody = {
      name: name.trim(),
      kind,
      user_id: kind === "person" && userId ? userId : null,
      hours,
      active,
      sort: existing?.sort ?? setup.resources.length,
      service_ids: serviceIds,
    };
    try {
      if (existing) await bookingsApi.updateResource(existing.id, body);
      else await bookingsApi.createResource(body);
      toast.success("Saved");
      onSaved();
    } catch (err) {
      toast.error(errorText(err));
      setBusy(false);
    }
  }

  async function remove() {
    if (!existing) return;
    setBusy(true);
    try {
      await bookingsApi.removeResource(existing.id);
      toast.success("Removed");
      onSaved();
    } catch (err) {
      toast.error(errorText(err));
      setBusy(false);
      setConfirmRemove(false);
    }
  }

  return (
    <>
      <Sheet
        title={existing ? `Edit ${existing.name}` : "Add staff / chair"}
        wide
        onClose={onClose}
        labelId="resource-title"
        footer={
          <>
            {existing && (
              <button type="button" className={`${BTN_DANGER} mr-auto`} onClick={() => setConfirmRemove(true)} disabled={busy}>
                Remove
              </button>
            )}
            <button type="button" className={BTN_SECONDARY} onClick={onClose} disabled={busy}>
              Cancel
            </button>
            <button type="button" className={BTN_PRIMARY} onClick={() => void save()} disabled={!canSave}>
              Save
            </button>
          </>
        }
      >
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Name" htmlFor="res-name">
              <input id="res-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={80} className={INPUT_CLS} placeholder="Ravi, Chair 2" />
            </Field>
            <Field label="Kind">
              <SegmentedControl aria-label="Kind" value={kind} onChange={setKind} options={(Object.keys(KIND_LABEL) as ResourceKind[]).map((k) => ({ value: k, label: KIND_LABEL[k] }))} />
            </Field>
          </div>
          {kind === "person" && (
            <Field label="Linked login (optional)" hint="This person then sees only their own column, and can mark Came / Didn't come.">
              <Select
                value={userId}
                onChange={setUserId}
                placeholder="Not linked"
                options={[{ value: "", label: "Not linked" }, ...people.map((t) => ({ value: t.user_id, label: t.name }))]}
              />
              {pickedMember && pickedMember.has_view === false && (
                <div className="mt-2">
                  <NoViewNotice name={pickedMember.name} />
                </div>
              )}
            </Field>
          )}
          <div className="flex items-center justify-between gap-3 rounded-xl border border-[#eef2f6] px-3 py-2">
            <span className="text-sm font-semibold text-ink">Taking bookings</span>
            <SwitchPill on={active} onChange={setActive} aria-label="Taking bookings" />
          </div>

          <fieldset>
            <legend className="mb-1 font-label text-xs font-bold text-ink-muted">Working hours ({DAY_SHORT[0]}–{DAY_SHORT[6]})</legend>
            <HoursEditor value={hours} onChange={setHours} idPrefix="hrs" />
          </fieldset>

          <fieldset>
            <legend className="mb-1 font-label text-xs font-bold text-ink-muted">Does these services</legend>
            {setup.services.length === 0 ? (
              <p className="text-sm text-ink-muted">No services yet. Add them in Services &amp; timings.</p>
            ) : (
              <ul className="grid gap-1.5 sm:grid-cols-2">
                {setup.services.map((s) => (
                  <li key={s.id}>
                    <label className="flex items-center gap-2 text-sm text-ink">
                      <input
                        type="checkbox"
                        className="h-4 w-4"
                        checked={serviceIds.includes(s.id)}
                        onChange={(e) => setServiceIds((cur) => (e.target.checked ? [...cur, s.id] : cur.filter((x) => x !== s.id)))}
                      />
                      {s.name}
                      {!s.active && <span className="text-xs text-ink-muted">(stopped)</span>}
                    </label>
                  </li>
                ))}
              </ul>
            )}
          </fieldset>
        </div>
      </Sheet>
      {confirmRemove && existing && (
        <ConfirmSheet
          title={`Remove ${existing.name}?`}
          body="They stop taking new bookings. Old bookings stay in the history."
          confirmLabel="Remove"
          tone="danger"
          busy={busy}
          onClose={() => setConfirmRemove(false)}
          onConfirm={() => void remove()}
        />
      )}
    </>
  );
}
