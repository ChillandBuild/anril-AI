"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Check, Eye, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Select } from "@/components/ui/Select";
import { api, type CallAlert, type CallAlertType } from "@/lib/api";
import { formatPhone, timeAgo } from "@/lib/utils";

const TYPE_LABEL: Record<CallAlertType, string> = {
  rude: "Rude or dismissive",
  wrong_info: "Wrong product info",
  crm_mismatch: "Wrap-up mismatch",
  no_proof: "Mark without proof",
  transcript_failed: "Couldn't transcribe",
  language_barrier: "Language barrier",
  lead_source_quality: "Bad lead source",
  tracks_swapped: "Tracks may be swapped",
};
const SERIOUS: CallAlertType[] = ["rude", "wrong_info"];

interface NeedsAttentionProps {
  onViewLead: (leadId: string) => void;
}

/** Admin-only list of call-scoring warnings: one place instead of a notification per call. */
export default function NeedsAttention({ onViewLead }: NeedsAttentionProps) {
  const [type, setType] = useState<CallAlertType | "">("");
  const [rows, setRows] = useState<CallAlert[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async (nextType: CallAlertType | "", nextPage: number) => {
    setLoading(true);
    try {
      const res = await api.calls.alerts({ type: nextType || undefined, page: nextPage });
      setRows((prev) => (nextPage === 1 ? res.data : [...prev, ...res.data]));
      setTotal(res.total);
      setPage(nextPage);
    } catch (err) {
      console.error("Failed to load call alerts:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(type, 1);
  }, [type, load]);

  async function markSeen(alert: CallAlert) {
    setBusyId(alert.id);
    try {
      await api.calls.markAlertSeen(alert.id);
      setRows((prev) => prev.filter((r) => r.id !== alert.id));
      setTotal((n) => Math.max(0, n - 1));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not mark as seen");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div id="needs-attention" className="bg-surface rounded-card p-6 shadow-card ring-1 ring-[#c4c7c7]/15">
      <div className="flex items-start justify-between gap-4 flex-wrap mb-4">
        <div>
          <h2 className="font-display text-base font-bold text-primary flex items-center gap-2">
            <AlertTriangle size={15} className="text-amber-600" /> Needs attention
            {total > 0 && (
              <span className="inline-flex min-w-5 h-5 items-center justify-center rounded-full bg-rose-600 px-1.5 font-label text-[10px] font-extrabold text-white">
                {total}
              </span>
            )}
          </h2>
          <p className="font-label text-xs text-on-surface-muted mt-0.5">
            Warnings from call scoring. You get one summary each morning; only rudeness and wrong product info alert you straight away.
          </p>
        </div>
        <Select
          size="sm"
          className="w-auto min-w-[180px]"
          value={type}
          onChange={(v) => setType(v as CallAlertType | "")}
          aria-label="Filter by type"
          options={[{ value: "", label: "All types" }, ...(Object.keys(TYPE_LABEL) as CallAlertType[]).map((t) => ({ value: t, label: TYPE_LABEL[t] }))]}
        />
      </div>

      {loading && rows.length === 0 ? (
        <div className="flex justify-center py-8"><Loader2 size={18} className="animate-spin text-[#94a3b8]" /></div>
      ) : rows.length === 0 ? (
        <p className="py-8 text-center font-body text-sm text-[#94a3b8]">Nothing needs attention.</p>
      ) : (
        <ul className="divide-y divide-[#f1f5f9]">
          {rows.map((a) => {
            const lead = a.call_logs?.leads;
            const leadId = a.call_logs?.lead_id;
            return (
              <li key={a.id} className="flex items-start gap-3 py-3">
                <span className={`mt-0.5 shrink-0 inline-flex items-center rounded-full border px-2 py-0.5 font-label text-[9px] font-bold ${SERIOUS.includes(a.type) ? "bg-rose-50 text-rose-700 border-rose-200" : "bg-amber-50 text-amber-700 border-amber-200"}`}>
                  {TYPE_LABEL[a.type]}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="font-body text-xs font-bold text-[#13284A] truncate">
                    {a.callers?.name ?? "All telecallers"}
                    {lead && <span className="font-semibold text-[#475569]"> · {lead.name || formatPhone(lead.phone ?? "")}</span>}
                  </p>
                  {a.quote && <p className="font-body text-[11px] text-[#334155] mt-0.5 break-words">{a.quote}</p>}
                  <p className="font-label text-[10px] text-[#94a3b8] mt-0.5">{timeAgo(a.created_at)}</p>
                </div>
                <div className="flex shrink-0 gap-1.5">
                  {leadId && (
                    <button type="button" onClick={() => onViewLead(leadId)} className="inline-flex items-center gap-1 rounded-lg border border-[#e2e8f0] bg-white px-2.5 py-1.5 font-label text-[10px] font-extrabold text-[#334155] hover:bg-[#f8fafc]">
                      <Eye size={11} /> Open
                    </button>
                  )}
                  <button type="button" disabled={busyId === a.id} onClick={() => void markSeen(a)} className="inline-flex items-center gap-1 rounded-lg bg-primary px-2.5 py-1.5 font-label text-[10px] font-extrabold text-white disabled:opacity-60">
                    {busyId === a.id ? <Loader2 size={11} className="animate-spin" /> : <Check size={11} />} Seen
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {rows.length < total && (
        <button type="button" onClick={() => void load(type, page + 1)} disabled={loading} className="mt-3 w-full rounded-lg border border-[#e2e8f0] py-2 font-label text-xs font-bold text-[#334155] hover:bg-[#f8fafc] disabled:opacity-60">
          {loading ? "Loading…" : "Load more"}
        </button>
      )}
    </div>
  );
}
