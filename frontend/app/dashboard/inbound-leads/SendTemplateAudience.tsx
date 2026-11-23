"use client";
import { useEffect, useMemo, useState } from "react";
import { Loader2, X } from "lucide-react";
import { api, type InboundLead, type InboundLeadFilters, type InboundResult } from "@/lib/api";
import { cn } from "@/lib/utils";

const INTEREST = [
  { value: "", label: "Any" },
  { value: "A", label: "🔥 Hot" },
  { value: "B", label: "Warm" },
  { value: "C", label: "Cold" },
];
const RESULT: { value: "" | InboundResult; label: string }[] = [
  { value: "", label: "Any" },
  { value: "none", label: "No result yet" },
  { value: "booked", label: "Booked" },
  { value: "paid", label: "Came / Paid" },
  { value: "lost", label: "Lost" },
];
const CAME_ON = [
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
  { value: "any", label: "Any time" },
];
const MAX_PEOPLE = 1000;

function istDate(daysBack: number): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date(Date.now() - (daysBack - 1) * 86_400_000));
}

/** "Booked customers, Hot, who came in the last 30 days." */
export function audienceWords(segment: string, result: string, cameOn: string): string {
  const who = RESULT.find((r) => r.value === result && r.value)?.label;
  const interest = INTEREST.find((i) => i.value === segment && i.value)?.label.replace("🔥 ", "");
  const parts = [`${who ? `${who} customers` : "Everyone"}`, interest ? `${interest} interest` : "any interest"];
  const when = cameOn === "any" ? "any time" : `the ${CAME_ON.find((c) => c.value === cameOn)?.label.toLowerCase()}`;
  return `${parts.join(", ")}, who came ${cameOn === "any" ? "at " : "in "}${when}.`;
}

/**
 * Send template, step 1: who gets it. Interest and Result chips, Came on, plus the tag / channel
 * filters already on the page. Shows how many will get it and how many said stop (they are left out).
 */
export function SendTemplateAudience({
  base,
  onClose,
  onNext,
}: {
  /** The page's other filters (tag, channel, ad, search). */
  base: InboundLeadFilters;
  onClose: () => void;
  onNext: (leads: InboundLead[], label: string) => void;
}) {
  const [segment, setSegment] = useState("");
  const [result, setResult] = useState<"" | InboundResult>("");
  const [cameOn, setCameOn] = useState("30");
  const [people, setPeople] = useState<InboundLead[] | null>(null);
  const [total, setTotal] = useState(0);

  const filters = useMemo<InboundLeadFilters>(() => ({
    ...base,
    segment: segment || undefined,
    result: result || undefined,
    date_from: cameOn === "any" ? undefined : istDate(Number(cameOn)),
    waiting: undefined,
  }), [base, segment, result, cameOn]);

  useEffect(() => {
    let live = true;
    setPeople(null);
    (async () => {
      const rows: InboundLead[] = [];
      let all = 0;
      for (let page = 1; rows.length < MAX_PEOPLE; page++) {
        const res = await api.inboundLeads.list({ ...filters, page, limit: 200 });
        all = res.total;
        rows.push(...res.data);
        if (res.data.length < 200 || rows.length >= res.total) break;
      }
      if (live) { setPeople(rows); setTotal(all); }
    })().catch(() => live && setPeople([]));
    return () => { live = false; };
  }, [filters]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const optedOut = (people ?? []).filter((p) => p.opted_out).length;
  const eligible = (people ?? []).filter((p) => !p.opted_out);
  const words = audienceWords(segment, result, cameOn);

  const chip = (on: boolean) =>
    cn("rounded-full border px-3 py-1 text-[12.5px] font-semibold transition",
      on ? "border-primary bg-primary/10 text-primary" : "border-[#e2e8f0] text-[#334155] hover:border-[#94a3b8]");

  return (
    <div className="fixed inset-0 z-dialog flex items-center justify-center bg-[#0A1528]/45 p-4" onMouseDown={onClose}>
      <div role="dialog" aria-modal="true" aria-labelledby="audience-title" onMouseDown={(e) => e.stopPropagation()}
        className="w-full max-w-[620px] rounded-2xl bg-white shadow-[0_30px_80px_-20px_rgba(10,21,40,0.45)]">
        <div className="flex items-start gap-3 px-6 pt-5">
          <div className="min-w-0 flex-1">
            <h2 id="audience-title" className="font-display text-[18px] font-bold text-[#0A1528]">Send WhatsApp template</h2>
            <p className="mt-0.5 text-[12.5px] text-[#64748b]">One message, sent once. Now or at a time you pick.</p>
          </div>
          <button onClick={onClose} aria-label="Close" className="rounded-lg p-1.5 text-[#64748b] hover:bg-slate-100"><X size={18} /></button>
        </div>
        <div className="space-y-3 px-6 py-4">
          <p className="font-label text-[10.5px] font-bold uppercase tracking-[0.08em] text-[#64748b]">1 · Who gets it</p>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="w-16 text-[12.5px] text-[#475467]">Interest</span>
            {INTEREST.map((i) => (
              <button key={i.value} type="button" aria-pressed={segment === i.value} onClick={() => setSegment(i.value)} className={chip(segment === i.value)}>{i.label}</button>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="w-16 text-[12.5px] text-[#475467]">Result</span>
            {RESULT.map((r) => (
              <button key={r.value} type="button" aria-pressed={result === r.value} onClick={() => setResult(r.value)} className={chip(result === r.value)}>{r.label}</button>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="w-16 text-[12.5px] text-[#475467]">Came on</span>
            {CAME_ON.map((c) => (
              <button key={c.value} type="button" aria-pressed={cameOn === c.value} onClick={() => setCameOn(c.value)} className={chip(cameOn === c.value)}>{c.label}</button>
            ))}
          </div>
          <div className="rounded-xl bg-primary-light/50 px-4 py-3">
            {people === null ? (
              <p className="flex items-center gap-2 text-[13px] text-[#475467]"><Loader2 size={14} className="animate-spin text-primary" /> Counting…</p>
            ) : (
              <>
                <p className="text-[13.5px] text-[#0A1528]">
                  <span className="font-display text-[20px] font-bold text-primary">{eligible.length.toLocaleString("en-IN")} {eligible.length === 1 ? "person" : "people"}</span>{" "}
                  will get this · {optedOut.toLocaleString("en-IN")} said stop and are left out
                </p>
                <p className="mt-0.5 text-[12.5px] text-[#475467]">In plain words: {words}</p>
                {total > MAX_PEOPLE && (
                  <p className="mt-1 text-[12px] text-[#b54708]">That&apos;s more than {MAX_PEOPLE.toLocaleString("en-IN")}. Narrow it down, or use Reach for a big campaign.</p>
                )}
              </>
            )}
          </div>
        </div>
        <div className="flex items-center justify-end gap-3 border-t border-[#eef1f5] px-6 py-4">
          <button type="button" onClick={onClose} className="h-10 rounded-xl border border-[#e2e8f0] px-5 text-[13.5px] font-semibold text-[#334155] hover:bg-slate-50">Cancel</button>
          <button type="button" disabled={!people || eligible.length === 0 || total > MAX_PEOPLE}
            onClick={() => onNext(eligible, words.replace(/\.$/, "").slice(0, 80))}
            className="h-10 rounded-xl bg-primary px-5 text-[13.5px] font-bold text-white hover:bg-primary-dark disabled:cursor-not-allowed disabled:opacity-45">
            Next: pick the template
          </button>
        </div>
      </div>
    </div>
  );
}
