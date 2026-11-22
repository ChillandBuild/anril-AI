"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import type { QrLink, QrPlace } from "@/lib/qrLinksApi";
import { MESSAGE_MAX, NAME_MAX, defaultFirstMessage, validateQrForm } from "@/lib/qrLinks";

const field =
  "w-full rounded-xl border border-border bg-white px-3 py-2 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary";

export interface QrFormResult {
  name: string;
  first_message: string;
  place_id: string | null;
}

/** New QR (link omitted) or Edit. The first message follows the name until the person types their own. */
export function QrForm({
  link, places, onSave, onCancel,
}: {
  link?: QrLink;
  places: QrPlace[];
  onSave: (v: QrFormResult) => Promise<void>;
  onCancel: () => void;
}) {
  const [name, setName] = useState(link?.name ?? "");
  const [message, setMessage] = useState(link?.first_message ?? defaultFirstMessage(""));
  const [messageEdited, setMessageEdited] = useState(Boolean(link));
  const [placeId, setPlaceId] = useState(link?.place_id ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [touched, setTouched] = useState(false);
  const problems = validateQrForm({ name, first_message: message });
  // An archived place stays pickable for the QR that already uses it.
  const options = link?.place_id && !places.some((p) => p.id === link.place_id)
    ? [...places, { id: link.place_id, name: link.place_name ?? "Old place" }]
    : places;

  function changeName(value: string) {
    setName(value);
    if (!messageEdited) setMessage(defaultFirstMessage(value));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setTouched(true);
    if (Object.keys(problems).length) return;
    setBusy(true);
    setError(null);
    try {
      await onSave({ name: name.trim(), first_message: message.trim(), place_id: placeId || null });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save. Please try again.");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4 rounded-card border border-primary/30 bg-white p-4 shadow-card" aria-label={link ? "Edit QR" : "New QR"}>
      <h2 className="font-display text-lg font-bold text-ink">{link ? "Edit QR" : "New QR"}</h2>
      <p className="text-sm text-ink-muted">The printed QR stays the same when you edit it. Only what the customer sends changes.</p>

      <div>
        <label htmlFor="qr-name" className="mb-1 block text-sm font-semibold text-ink">Place name</label>
        <input id="qr-name" value={name} onChange={(e) => changeName(e.target.value)} maxLength={NAME_MAX} placeholder="Table 4, Front counter, Mall stall"
          className={field} aria-invalid={touched && !!problems.name} aria-describedby={touched && problems.name ? "qr-name-err" : undefined} />
        {touched && problems.name && <p id="qr-name-err" className="mt-1 text-sm text-danger">{problems.name}</p>}
      </div>

      {options.length > 0 && (
        <div>
          <label htmlFor="qr-place" className="mb-1 block text-sm font-semibold text-ink">Stock place (optional)</label>
          <select id="qr-place" value={placeId} onChange={(e) => setPlaceId(e.target.value)} className={field}>
            <option value="">None</option>
            {options.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </div>
      )}

      <div>
        <label htmlFor="qr-msg" className="mb-1 block text-sm font-semibold text-ink">First message the customer sends</label>
        <textarea id="qr-msg" value={message} rows={3} maxLength={MESSAGE_MAX}
          onChange={(e) => { setMessage(e.target.value); setMessageEdited(true); }}
          className={field} aria-invalid={touched && !!problems.first_message} aria-describedby={touched && problems.first_message ? "qr-msg-err" : undefined} />
        <p className="mt-1 text-xs text-ink-muted">We add a small code at the end so we know which QR they scanned.</p>
        {touched && problems.first_message && <p id="qr-msg-err" className="mt-1 text-sm text-danger">{problems.first_message}</p>}
      </div>

      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      <div className="flex flex-wrap justify-end gap-2">
        <button type="button" onClick={onCancel} className="inline-flex h-11 items-center rounded-xl border border-border px-4 text-sm font-semibold text-ink hover:bg-surface-low">Cancel</button>
        <button type="submit" disabled={busy} className="inline-flex h-11 items-center gap-2 rounded-xl bg-primary px-4 text-sm font-semibold text-white hover:bg-primary-dark disabled:opacity-60">
          {busy && <Loader2 size={16} className="animate-spin" />} {link ? "Save" : "Make QR"}
        </button>
      </div>
    </form>
  );
}
