"use client";

// v9.2 #74: "⏳ Waiting to send" — bills made while the internet was down. They go out on their own when the
// device is back online (and whenever this list is shown); each keeps its "send once" key, so nothing doubles.
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { dropBill, queuedBills, sendQueued, type QueuedBill } from "@/lib/offlineBills";

function when(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit", hour12: true });
}

export function WaitingBills({ onSent }: { onSent?: () => void }) {
  const [list, setList] = useState<QueuedBill[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmDrop, setConfirmDrop] = useState<string | null>(null);
  const running = useRef(false);

  const refresh = useCallback(() => setList(queuedBills()), []);

  const flush = useCallback(async (only?: string) => {
    if (running.current) return;
    if (!queuedBills().some((b) => (only ? b.client_ref === only : !b.error))) return;
    running.current = true;
    setBusy(only ?? "all");
    try {
      const out = await sendQueued((body) => api.orders.createBill(body), only);
      if (out.sent) {
        toast.success(out.sent === 1 ? "1 bill saved that was waiting to send" : `${out.sent} bills saved that were waiting to send`);
        onSent?.();
      }
      if (out.failed) toast.error("A waiting bill couldn't be saved. See the reason below.");
      if (only && out.offline) toast.error("Still no internet. It will go out when you're back online.");
    } finally {
      running.current = false;
      setBusy(null);
      refresh();
    }
  }, [onSent, refresh]);

  useEffect(() => {
    refresh();
    void flush();
    const onChange = () => refresh();
    const onOnline = () => void flush();
    window.addEventListener("anril-offline-bills", onChange);
    window.addEventListener("storage", onChange);
    window.addEventListener("online", onOnline);
    return () => {
      window.removeEventListener("anril-offline-bills", onChange);
      window.removeEventListener("storage", onChange);
      window.removeEventListener("online", onOnline);
    };
  }, [flush, refresh]);

  if (!list.length) return null;
  return (
    <section aria-label="Bills waiting to send" className="rounded-2xl border border-amber-200 bg-amber-50 p-3">
      <p className="font-label text-xs font-bold text-amber-900">
        ⏳ Waiting to send ({list.length}) · saved on this device, they go out when the internet is back
      </p>
      <ul className="mt-2 space-y-1.5">
        {list.map((b) => (
          <li key={b.client_ref} className="flex flex-wrap items-center gap-2 rounded-xl bg-white px-3 py-2 text-sm">
            <span className="min-w-0 flex-1">
              <span className="font-semibold text-[#0A1528]">{b.label}</span>
              <span className="ml-2 text-xs text-[#64748b]">billed {when(b.made_at)}</span>
              {b.error && <span className="block text-xs text-red-700">Not saved: {b.error}</span>}
            </span>
            <button type="button" onClick={() => void flush(b.client_ref)} disabled={busy !== null}
              className="inline-flex items-center gap-1 rounded-lg border border-[#e2e8f0] px-2.5 py-1 font-label text-xs font-bold text-[#334155] hover:bg-slate-50 disabled:opacity-50">
              {busy === b.client_ref && <Loader2 size={12} className="animate-spin" />} Send now
            </button>
            {confirmDrop === b.client_ref ? (
              <button type="button" onClick={() => { dropBill(b.client_ref); setConfirmDrop(null); refresh(); }}
                className="rounded-lg bg-red-600 px-2.5 py-1 font-label text-xs font-bold text-white hover:bg-red-700">
                Sure? Remove it
              </button>
            ) : (
              <button type="button" onClick={() => setConfirmDrop(b.client_ref)}
                className="rounded-lg px-2.5 py-1 font-label text-xs font-bold text-red-700 hover:bg-red-50">
                Remove
              </button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
