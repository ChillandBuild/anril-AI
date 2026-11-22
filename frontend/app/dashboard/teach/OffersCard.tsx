"use client";
import { useState } from "react";
import { Loader2, Plus } from "lucide-react";
import { toast } from "sonner";
import { api, type TeachOffer } from "@/lib/api";
import { addDays, offerLabel, todayIst } from "./teachLogic";

const FIELD =
  "w-full rounded-xl border border-border-subtle bg-white px-3 py-2 font-body text-sm text-ink focus:outline-none focus:ring-2 focus:ring-primary/20";
const SMALL_BTN =
  "inline-flex min-h-9 items-center rounded-lg border border-border-subtle bg-white px-3 font-label text-xs font-bold text-ink hover:border-primary/40";
const PILL: Record<TeachOffer["status"], string> = {
  live: "bg-emerald-50 text-emerald-800",
  upcoming: "bg-amber-50 text-amber-800",
  ended: "bg-surface-low text-ink-secondary",
};

function message(e: unknown) {
  return e instanceof Error && e.message ? e.message : "Could not save. Please try again.";
}

function OfferForm({ offer, onDone }: { offer: TeachOffer | null; onDone: (saved: boolean) => void }) {
  const today = todayIst();
  const [title, setTitle] = useState(offer?.title ?? "");
  const [details, setDetails] = useState(offer?.details ?? "");
  const [startsOn, setStartsOn] = useState(offer?.starts_on ?? today);
  const [endsOn, setEndsOn] = useState(offer?.ends_on ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    const body = { title, details: details.trim() || null, starts_on: startsOn || null, ends_on: endsOn || null };
    try {
      if (offer) await api.aiTeach.saveOffer(offer.id, body);
      else await api.aiTeach.addOffer(body);
      toast.success(offer ? "Offer updated" : "Offer added");
      onDone(true);
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} className="space-y-2 rounded-xl border border-primary/25 bg-primary/[0.03] p-3">
      <label className="block font-label text-xs font-bold text-ink">
        Offer name
        <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={120} className={`${FIELD} mt-1 font-normal`} placeholder="e.g. Diwali silk sale" />
      </label>
      <label className="block font-label text-xs font-bold text-ink">
        Details (optional)
        <textarea value={details} onChange={(e) => setDetails(e.target.value)} maxLength={500} rows={2} className={`${FIELD} mt-1 resize-y font-normal`}
          placeholder="e.g. 20% off all silk sarees, in store and online" />
      </label>
      <div className="grid grid-cols-2 gap-2">
        <label className="block font-label text-xs font-bold text-ink">
          Starts
          <input type="date" value={startsOn} onChange={(e) => setStartsOn(e.target.value)} className={`${FIELD} mt-1 font-normal`} />
        </label>
        <label className="block font-label text-xs font-bold text-ink">
          Ends (required)
          <input type="date" value={endsOn} min={startsOn || today} max={addDays(startsOn || today, 365)}
            onChange={(e) => setEndsOn(e.target.value)} className={`${FIELD} mt-1 font-normal`} />
        </label>
      </div>
      <p className="font-body text-xs text-ink-secondary">The AI mentions this offer only until the end date, then stops by itself.</p>
      {error && <p role="alert" className="font-body text-xs text-danger">{error}</p>}
      <div className="flex gap-2">
        <button type="submit" disabled={busy || !title.trim() || !endsOn} className="btn-primary min-h-9 disabled:opacity-50">
          {busy && <Loader2 size={14} className="animate-spin" aria-hidden />} Save
        </button>
        <button type="button" onClick={() => onDone(false)} className="btn-secondary min-h-9">Cancel</button>
      </div>
    </form>
  );
}

export function OffersCard({ offers, canEdit, onChange }: { offers: TeachOffer[]; canEdit: boolean; onChange: () => void }) {
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);

  async function run(action: () => Promise<unknown>, done: string) {
    try {
      await action();
      toast.success(done);
      setConfirming(null);
      onChange();
    } catch (err) {
      toast.error(message(err));
    }
  }

  return (
    <section className="card space-y-3" aria-labelledby="offers-h">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 id="offers-h" className="font-display text-base font-bold text-ink">Offers on now</h2>
          <p className="font-body text-sm text-ink-secondary">The AI tells customers only about these, and only until the end date.</p>
        </div>
      </div>
      {canEdit && !adding && (
        <button type="button" onClick={() => setAdding(true)} className="btn-primary">
          <Plus size={14} aria-hidden /> Add offer (needs an end date)
        </button>
      )}
      {adding && <OfferForm offer={null} onDone={(saved) => { setAdding(false); if (saved) onChange(); }} />}

      {offers.length === 0 && !adding && (
        <p className="rounded-xl bg-surface-low px-3 py-4 font-body text-sm text-ink-secondary">
          No offers. The AI will not mention any discount or deal until you add one.
        </p>
      )}

      <ul className="space-y-2">
        {offers.map((o) => (
          <li key={o.id} className={`rounded-xl border border-border-subtle p-3 ${o.status === "ended" ? "opacity-70" : ""}`}>
            {editing === o.id ? (
              <OfferForm offer={o} onDone={(saved) => { setEditing(null); if (saved) onChange(); }} />
            ) : (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <p className="break-words font-body text-sm font-bold text-ink">{o.title}</p>
                  <span className={`rounded-full px-2 py-0.5 font-label text-xs font-bold ${PILL[o.status]}`}>{offerLabel(o)}</span>
                  {o.source === "reach" && <span className="font-label text-xs text-ink-secondary">from Reach</span>}
                </div>
                {o.details && <p className="mt-1 whitespace-pre-wrap break-words font-body text-sm text-ink-secondary">{o.details}</p>}
                {canEdit && (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {confirming === o.id ? (
                      <>
                        <button type="button" onClick={() => run(() => api.aiTeach.deleteOffer(o.id), "Offer deleted")} className={`${SMALL_BTN} border-danger text-danger`}>
                          Yes, delete
                        </button>
                        <button type="button" onClick={() => setConfirming(null)} className={SMALL_BTN}>Keep</button>
                      </>
                    ) : (
                      <>
                        {o.status !== "ended" && (
                          <button type="button" onClick={() => setEditing(o.id)} className={SMALL_BTN}>Edit</button>
                        )}
                        {o.status !== "ended" && (
                          <button type="button" onClick={() => run(() => api.aiTeach.endOffer(o.id), "Offer ended. The AI stopped mentioning it.")} className={SMALL_BTN}>
                            End now
                          </button>
                        )}
                        <button type="button" onClick={() => setConfirming(o.id)} className={SMALL_BTN}>Delete</button>
                      </>
                    )}
                  </div>
                )}
              </>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
