"use client";
import { useEffect, useState } from "react";
import { Search, X } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { formatPhone } from "@/lib/utils";
import QuickTimePicker from "../components/wrapup/QuickTimePicker";
import { lookupCustomers, worthLooking, type DialMatch } from "../lib/dialLookup";

const INPUT = "w-full rounded-xl border border-[#e2e8f0] bg-white px-3 py-2 font-body text-xs focus:outline-none focus:ring-2 focus:ring-primary";
const PRIMARY = "rounded-xl bg-primary px-4 py-2 font-label text-xs font-bold text-white disabled:opacity-40";
const LOOKUP_DELAY_MS = 300;

function Shell({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-dialog flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true" aria-label={title}>
      <div className="w-full max-w-md space-y-4 rounded-3xl bg-white p-5 shadow-xl">
        <div className="flex items-center justify-between">
          <h3 className="font-display text-sm font-extrabold text-[#13284A]">{title}</h3>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-full p-1 text-[#94a3b8] hover:bg-[#f1f5f9]"><X size={16} /></button>
        </div>
        {children}
      </div>
    </div>
  );
}

function errorText(e: unknown, fallback: string): string {
  return e instanceof Error && e.message ? e.message : fallback;
}

/** "+ Schedule a call" for any customer: find them like the dial page does, pick a time, say why. */
export function ScheduleCallModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [text, setText] = useState("");
  const [matches, setMatches] = useState<DialMatch[]>([]);
  const [picked, setPicked] = useState<DialMatch | null>(null);
  const [when, setWhen] = useState<string | null>(null);
  const [why, setWhy] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (picked || !worthLooking(text)) {
      setMatches([]);
      return;
    }
    let live = true;
    const t = setTimeout(() => {
      lookupCustomers(text).then((r) => live && setMatches(r.matches)).catch(() => live && setMatches([]));
    }, LOOKUP_DELAY_MS);
    return () => { live = false; clearTimeout(t); };
  }, [text, picked]);

  async function save() {
    if (!picked || !when) return;
    setSaving(true);
    try {
      await api.followUps.scheduleCallback(picked.id, when, why.trim());
      toast.success("Call scheduled");
      onSaved();
      onClose();
    } catch (e) {
      toast.error(errorText(e, "Couldn't schedule the call"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Shell title="Schedule a call" onClose={onClose}>
      {picked ? (
        <div className="flex items-center justify-between rounded-xl border border-[#e2e8f0] bg-[#f8fafc] px-3 py-2">
          <span className="font-body text-xs font-semibold text-[#1e293b]">{picked.name || "Unnamed"} · {picked.phone ? formatPhone(picked.phone) : ""}</span>
          <button type="button" onClick={() => setPicked(null)} className="font-label text-[10px] font-bold text-primary">Change</button>
        </div>
      ) : (
        <div className="space-y-2">
          <div className="relative">
            <Search size={13} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#94a3b8]" />
            <input autoFocus value={text} onChange={(e) => setText(e.target.value)} placeholder="Name or phone number" className={`${INPUT} pl-8`} />
          </div>
          {matches.length > 0 && (
            <ul className="max-h-48 divide-y divide-[#f1f5f9] overflow-auto rounded-xl border border-[#e2e8f0]">
              {matches.map((m) => (
                <li key={m.id}>
                  <button type="button" onClick={() => setPicked(m)} className="flex w-full items-center justify-between px-3 py-2 text-left hover:bg-[#f8fafc]">
                    <span className="font-body text-xs font-semibold text-[#1e293b]">{m.name || "Unnamed"}</span>
                    <span className="font-label text-[10px] text-[#94a3b8]">{m.phone ? formatPhone(m.phone) : ""}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {worthLooking(text) && matches.length === 0 && <p className="font-label text-[10px] text-[#94a3b8]">No customer found.</p>}
        </div>
      )}
      <div>
        <p className="mb-1 font-label text-[10px] font-extrabold uppercase tracking-wider text-[#94a3b8]">When *</p>
        <QuickTimePicker value={when} onChange={setWhen} now={new Date()} />
      </div>
      <div>
        <p className="mb-1 font-label text-[10px] font-extrabold uppercase tracking-wider text-[#94a3b8]">Why (optional)</p>
        <input value={why} maxLength={500} onChange={(e) => setWhy(e.target.value)} placeholder="e.g. Asked to call after the weekend" className={INPUT} />
      </div>
      <div className="flex justify-end gap-2">
        <button type="button" onClick={onClose} className="rounded-xl px-4 py-2 font-label text-xs font-bold text-[#475569]">Cancel</button>
        <button type="button" disabled={!picked || !when || saving} onClick={save} className={PRIMARY}>{saving ? "Saving…" : "Schedule"}</button>
      </div>
    </Shell>
  );
}

/** "Move": pick a new time for a scheduled call. */
export function MoveCallModal({ jobId, name, onClose, onSaved }: { jobId: string; name: string; onClose: () => void; onSaved: () => void }) {
  const [when, setWhen] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    if (!when) return;
    setSaving(true);
    try {
      await api.followUps.rescheduleCallback(jobId, when);
      toast.success("Call moved");
      onSaved();
      onClose();
    } catch (e) {
      toast.error(errorText(e, "Couldn't move the call"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Shell title={`Move call with ${name}`} onClose={onClose}>
      <QuickTimePicker value={when} onChange={setWhen} now={new Date()} />
      <div className="flex justify-end gap-2">
        <button type="button" onClick={onClose} className="rounded-xl px-4 py-2 font-label text-xs font-bold text-[#475569]">Cancel</button>
        <button type="button" disabled={!when || saving} onClick={save} className={PRIMARY}>{saving ? "Saving…" : "Move"}</button>
      </div>
    </Shell>
  );
}
