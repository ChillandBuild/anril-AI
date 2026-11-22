"use client";
import { useState } from "react";
import { Plus } from "lucide-react";
import { toast } from "sonner";
import { SwitchPill } from "@/components/ui/controls";
import { bookingsApi, type BookingService, type BookingSetup, type ServiceBody } from "@/lib/bookingsApi";
import { paiseToRupeesText, rupeesTextToPaise, rupees } from "./bookingsLogic";
import { BTN_DANGER, BTN_PRIMARY, BTN_SECONDARY, ConfirmSheet, Field, INPUT_CLS, Notice, Sheet, errorText } from "./bookingsUi";

/** What people can book: name, minutes, price, advance, gap after, and who can do it. */
export function ServicesTab({ setup, canManage, canSeeMoney, onChanged }: { setup: BookingSetup; canManage: boolean; canSeeMoney: boolean; onChanged: () => void }) {
  const [editing, setEditing] = useState<BookingService | "new" | null>(null);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="font-display text-lg font-bold text-ink">Services &amp; timings</h2>
        {canManage && (
          <button type="button" className={BTN_PRIMARY} onClick={() => setEditing("new")}>
            <Plus size={16} aria-hidden /> Add service
          </button>
        )}
      </div>
      {setup.services.length === 0 && <Notice>{canManage ? "No services yet. Add what people can book, like a haircut or a consultation." : "No services yet."}</Notice>}
      <ul className="grid gap-3 md:grid-cols-2">
        {setup.services.map((s) => {
          const who = setup.resources.filter((r) => s.resource_ids.includes(r.id)).map((r) => r.name);
          return (
            <li key={s.id} className="min-w-0 rounded-2xl border border-[#e8edf2] bg-white p-4 shadow-sm">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <h3 className="truncate font-display text-base font-bold text-ink">{s.name}</h3>
                  <p className="text-sm text-ink-muted">
                    {s.duration_min} min{s.gap_after_min > 0 ? ` + ${s.gap_after_min} min gap` : ""}
                    {canSeeMoney && typeof s.price_paise === "number" && s.price_paise > 0 ? ` · ${rupees(s.price_paise)}` : ""}
                    {canSeeMoney && typeof s.advance_paise === "number" && s.advance_paise > 0 ? ` · ${rupees(s.advance_paise)} advance` : ""}
                    {!s.active ? " · Not offered" : ""}
                  </p>
                </div>
                {canManage && (
                  <button type="button" className={BTN_SECONDARY} onClick={() => setEditing(s)}>
                    Edit
                  </button>
                )}
              </div>
              <p className="mt-2 text-sm text-ink-secondary">{who.length ? `Done by ${who.join(", ")}` : "Nobody does this yet"}</p>
            </li>
          );
        })}
      </ul>
      {editing && (
        <ServiceEditor
          key={editing === "new" ? "new" : editing.id}
          existing={editing === "new" ? null : editing}
          setup={setup}
          canSeeMoney={canSeeMoney}
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

function ServiceEditor({ existing, setup, canSeeMoney, onClose, onSaved }: { existing: BookingService | null; setup: BookingSetup; canSeeMoney: boolean; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(existing?.name ?? "");
  const [minutes, setMinutes] = useState(String(existing?.duration_min ?? 30));
  const [price, setPrice] = useState(paiseToRupeesText(existing?.price_paise));
  const [advance, setAdvance] = useState(paiseToRupeesText(existing?.advance_paise));
  const [gap, setGap] = useState(String(existing?.gap_after_min ?? 0));
  const [active, setActive] = useState(existing?.active ?? true);
  const [resourceIds, setResourceIds] = useState<string[]>(existing?.resource_ids ?? setup.resources.filter((r) => r.active).map((r) => r.id));
  const [busy, setBusy] = useState(false);
  const [confirmStop, setConfirmStop] = useState(false);

  const mins = Number(minutes);
  const gapN = Number(gap);
  const priceP = rupeesTextToPaise(price);
  const advP = rupeesTextToPaise(advance);
  const problem =
    !name.trim() ? "Give it a name."
    : !Number.isInteger(mins) || mins < 5 || mins > 600 ? "Minutes must be between 5 and 600."
    : !Number.isInteger(gapN) || gapN < 0 || gapN > 240 ? "The gap must be between 0 and 240 minutes."
    : canSeeMoney && (priceP === null || advP === null) ? "Enter prices as plain numbers."
    : canSeeMoney && priceP !== null && advP !== null && priceP > 0 && advP > priceP ? "The advance cannot be more than the price."
    : null;

  async function save() {
    if (problem) return;
    setBusy(true);
    const body: ServiceBody = {
      name: name.trim(),
      duration_min: mins,
      gap_after_min: gapN,
      resource_ids: resourceIds,
      active,
      // Money is only sent by people who can see it; the server keeps the old amounts otherwise.
      ...(canSeeMoney ? { price_paise: priceP ?? 0, advance_paise: advP ?? 0 } : {}),
    };
    try {
      if (existing) await bookingsApi.updateService(existing.id, body);
      else await bookingsApi.createService(body);
      toast.success("Saved");
      onSaved();
    } catch (err) {
      toast.error(errorText(err));
      setBusy(false);
    }
  }

  async function stop() {
    if (!existing) return;
    setBusy(true);
    try {
      await bookingsApi.removeService(existing.id);
      toast.success("Service stopped");
      onSaved();
    } catch (err) {
      toast.error(errorText(err));
      setBusy(false);
      setConfirmStop(false);
    }
  }

  return (
    <>
      <Sheet
        title={existing ? `Edit ${existing.name}` : "Add service"}
        wide
        onClose={onClose}
        labelId="service-title"
        footer={
          <>
            {existing && existing.active && (
              <button type="button" className={`${BTN_DANGER} mr-auto`} onClick={() => setConfirmStop(true)} disabled={busy}>
                Stop offering
              </button>
            )}
            <button type="button" className={BTN_SECONDARY} onClick={onClose} disabled={busy}>
              Cancel
            </button>
            <button type="button" className={BTN_PRIMARY} onClick={() => void save()} disabled={busy || problem !== null}>
              Save
            </button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="Name" htmlFor="svc-name">
            <input id="svc-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={120} className={INPUT_CLS} placeholder="Haircut" />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="How long (minutes)" htmlFor="svc-min">
              <input id="svc-min" inputMode="numeric" value={minutes} onChange={(e) => setMinutes(e.target.value)} className={INPUT_CLS} />
            </Field>
            <Field label="Gap after (minutes)" htmlFor="svc-gap" hint="Kept free after each booking, e.g. to clean up.">
              <input id="svc-gap" inputMode="numeric" value={gap} onChange={(e) => setGap(e.target.value)} className={INPUT_CLS} />
            </Field>
            {canSeeMoney && (
              <>
                <Field label="Price (₹)" htmlFor="svc-price">
                  <input id="svc-price" inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} className={INPUT_CLS} placeholder="0" />
                </Field>
                <Field label="Advance to hold the time (₹)" htmlFor="svc-adv" hint="0 means no advance.">
                  <input id="svc-adv" inputMode="decimal" value={advance} onChange={(e) => setAdvance(e.target.value)} className={INPUT_CLS} placeholder="0" />
                </Field>
              </>
            )}
          </div>
          {existing && (
            <div className="flex items-center justify-between gap-3 rounded-xl border border-[#eef2f6] px-3 py-2">
              <span className="text-sm font-semibold text-ink">Offered to customers</span>
              <SwitchPill on={active} onChange={setActive} aria-label="Offered to customers" />
            </div>
          )}
          <fieldset>
            <legend className="mb-1 font-label text-xs font-bold text-ink-muted">Who can do it</legend>
            {setup.resources.length === 0 ? (
              <p className="text-sm text-ink-muted">Add a staff member or chair first.</p>
            ) : (
              <ul className="grid gap-1.5 sm:grid-cols-2">
                {setup.resources.map((r) => (
                  <li key={r.id}>
                    <label className="flex items-center gap-2 text-sm text-ink">
                      <input
                        type="checkbox"
                        className="h-4 w-4"
                        checked={resourceIds.includes(r.id)}
                        onChange={(e) => setResourceIds((cur) => (e.target.checked ? [...cur, r.id] : cur.filter((x) => x !== r.id)))}
                      />
                      {r.name}
                    </label>
                  </li>
                ))}
              </ul>
            )}
          </fieldset>
          {problem && <Notice tone="amber">{problem}</Notice>}
        </div>
      </Sheet>
      {confirmStop && existing && (
        <ConfirmSheet
          title={`Stop offering ${existing.name}?`}
          body="Customers can no longer book it. Old bookings keep it."
          confirmLabel="Stop offering"
          tone="danger"
          busy={busy}
          onClose={() => setConfirmStop(false)}
          onConfirm={() => void stop()}
        />
      )}
    </>
  );
}
