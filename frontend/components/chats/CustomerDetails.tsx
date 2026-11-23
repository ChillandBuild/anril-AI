"use client";
import { useEffect, useRef, useState } from "react";
import { Pencil } from "lucide-react";
import { toast } from "sonner";
import { api, type LeadDetailField, type LeadDetails } from "@/lib/api";

const VALUE_MAX = 120;

const BTN_SAVE =
  "inline-flex h-8 items-center rounded-lg bg-primary px-3 text-[12px] font-bold text-white hover:bg-primary-dark disabled:opacity-50";
const BTN_CANCEL =
  "inline-flex h-8 items-center rounded-lg border border-[#e2e8f0] bg-white px-3 text-[12px] font-bold text-[#0A1528] hover:bg-[#f8fafc]";
const INPUT =
  "h-8 min-w-0 w-full rounded-lg border border-[#e2e8f0] bg-white px-2.5 text-[12.5px] text-[#0A1528] placeholder:text-[#94a3b8] focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/15";

function SourceMark({ field }: { field: LeadDetailField }) {
  if (field.by === "ai") {
    return <span className="block text-[11px] font-semibold text-primary">{"🤖 from chat"}</span>;
  }
  if (field.by === "staff") {
    return <span className="block text-[11px] text-[#64748b]">{`by ${field.name ?? "your team"}`}</span>;
  }
  return <span className="block text-[11px] text-[#64748b]">from a form</span>;
}

/**
 * The customer details on the About panel: what the AI agent picked up in the chat, what staff typed, and what a form
 * asked. Staff can change or add one; a change stops the AI from writing over it.
 */
export function CustomerDetails({ leadId, canEdit, version }: { leadId: string; canEdit: boolean; version?: string }) {
  const [details, setDetails] = useState<LeadDetails | null>(null);
  const [failed, setFailed] = useState(false);
  const [retry, setRetry] = useState(0);
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [addKey, setAddKey] = useState("");
  const [addValue, setAddValue] = useState("");
  const currentLead = useRef(leadId);
  currentLead.current = leadId;
  const versionRef = useRef(version);
  versionRef.current = version;
  const firstVersion = useRef(version);

  // Reload when the customer changes (or on Try again). A reply for an older customer is ignored.
  useEffect(() => {
    let alive = true;
    firstVersion.current = versionRef.current; // a new customer: their current details are this load's
    setDetails(null);
    setFailed(false);
    setEditingKey(null);
    setAdding(false);
    api.leadDetails
      .get(leadId)
      .then((d) => { if (alive) setDetails(d); })
      .catch(() => { if (alive) setFailed(true); });
    return () => { alive = false; };
  }, [leadId, retry]);

  // The AI agent saves details while the chat is open: when the customer's saved details change, refresh quietly
  // (no loading bar, and not while someone is typing a change).
  useEffect(() => {
    if (version === firstVersion.current || editingKey || adding) return;
    firstVersion.current = version;
    let alive = true;
    api.leadDetails.get(leadId).then((d) => { if (alive) setDetails(d); }).catch(() => {});
    return () => { alive = false; };
  }, [version, leadId, editingKey, adding]);

  async function save(key: string, value: string): Promise<boolean> {
    setBusy(true);
    try {
      const next = await api.leadDetails.set(leadId, key, value.trim());
      if (currentLead.current === leadId) setDetails(next);
      toast.success("Saved");
      return true;
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't save that");
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function commitEdit(key: string) {
    if (busy) return;
    if (await save(key, draft)) setEditingKey(null);
  }

  async function commitAdd() {
    if (busy || !addKey || !addValue.trim()) return;
    if (await save(addKey, addValue)) {
      setAdding(false);
      setAddValue("");
    }
  }

  function startAdd() {
    setAddKey(details?.addable[0]?.key ?? "");
    setAddValue("");
    setAdding(true);
  }

  if (failed) {
    return (
      <p className="mt-2.5 text-[11.5px] text-[#94a3b8]">
        Couldn&apos;t load details.{" "}
        <button type="button" onClick={() => { setFailed(false); setRetry((n) => n + 1); }} className="font-semibold text-[#64748b] underline">
          Try again
        </button>
      </p>
    );
  }

  if (!details) {
    return <div className="mt-2.5 h-4 w-2/3 animate-pulse rounded bg-[#eef1f5]" aria-hidden />;
  }

  const { fields, addable } = details;
  const selectedAddKey = addable.some((a) => a.key === addKey) ? addKey : (addable[0]?.key ?? "");
  const addBlock =
    canEdit && addable.length > 0 ? (
      adding ? (
        <div className="mt-2 space-y-2 rounded-xl border border-[#e2e8f0] bg-white p-2.5">
          <div className="flex gap-2">
            <select
              aria-label="Which detail"
              value={selectedAddKey}
              onChange={(e) => setAddKey(e.target.value)}
              className="h-8 shrink-0 rounded-lg border border-[#e2e8f0] bg-white px-2 text-[12.5px] text-[#0A1528] focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/15"
            >
              {addable.map((a) => (
                <option key={a.key} value={a.key}>{a.label}</option>
              ))}
            </select>
            <input
              value={addValue}
              onChange={(e) => setAddValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") { e.preventDefault(); void commitAdd(); }
                if (e.key === "Escape") setAdding(false);
              }}
              maxLength={VALUE_MAX}
              aria-label="Value"
              placeholder="Type the detail"
              autoFocus
              className={INPUT}
            />
          </div>
          <div className="flex gap-2">
            <button type="button" onClick={() => void commitAdd()} disabled={busy || !addValue.trim()} className={BTN_SAVE}>Save</button>
            <button type="button" onClick={() => setAdding(false)} className={BTN_CANCEL}>Cancel</button>
          </div>
        </div>
      ) : (
        <button type="button" onClick={startAdd} className="mt-2 text-[12px] font-semibold text-primary hover:underline">
          ＋ Add a detail
        </button>
      )
    ) : null;

  if (fields.length === 0) {
    return (
      <div>
        <p className="mt-2 text-[11.5px] text-[#94a3b8]">Details the AI agent picks up in the chat show here.</p>
        {addBlock}
      </div>
    );
  }

  return (
    <div>
      <dl className="mt-2.5 space-y-1.5">
        {fields.map((f) => (
          <div key={f.key} className="grid grid-cols-[88px_minmax(0,1fr)] items-start gap-x-2 text-[12.5px]">
            <dt className="pt-px leading-snug text-[#64748b]">{f.label}</dt>
            {editingKey === f.key ? (
              <dd className="flex min-w-0 flex-wrap items-center gap-1.5">
                <input
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") { e.preventDefault(); void commitEdit(f.key); }
                    if (e.key === "Escape") setEditingKey(null);
                  }}
                  maxLength={VALUE_MAX}
                  aria-label={`New value for ${f.label}`}
                  placeholder="Empty clears it"
                  autoFocus
                  className={INPUT}
                />
                <button type="button" onClick={() => void commitEdit(f.key)} disabled={busy} className={BTN_SAVE}>Save</button>
                <button type="button" onClick={() => setEditingKey(null)} className={BTN_CANCEL}>Cancel</button>
              </dd>
            ) : (
              <dd className="flex min-w-0 items-start gap-1.5">
                <span className="min-w-0 flex-1">
                  <span className="block break-words font-semibold leading-snug text-[#0A1528]">{f.value}</span>
                  <SourceMark field={f} />
                </span>
                {canEdit && (
                  <button
                    type="button"
                    aria-label={`Change ${f.label}`}
                    disabled={busy}
                    onClick={() => { setDraft(f.value); setEditingKey(f.key); }}
                    className="shrink-0 rounded p-0.5 text-[#94a3b8] hover:bg-slate-100 hover:text-[#0A1528] disabled:opacity-45"
                  >
                    <Pencil size={12} />
                  </button>
                )}
              </dd>
            )}
          </div>
        ))}
      </dl>
      {fields.some((f) => f.by === "ai") && (
        <p className="mt-2 text-[11.5px] text-[#64748b]">
          The AI agent filled these from the chat. Change one and the AI won&apos;t write over it.
        </p>
      )}
      {addBlock}
    </div>
  );
}
