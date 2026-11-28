"use client";
import Link from "next/link";
import { Loader2 } from "lucide-react";
import { formatPhone } from "@/lib/utils";
import { callResultKey, callResultLabel } from "@/lib/call-wrapup";
import { SEGMENT_WORD } from "../lib/dialLookup";
import { stateTone, worthChecking, type DialCheckRow, type DialCheckState } from "../lib/dialCheck";

const MARK: Record<DialCheckRow["state"], string> = { ok: "✓", blocked: "⛔", warn: "!", not_checked: "–" };
const TONE_CLASS: Record<ReturnType<typeof stateTone>, string> = {
  ok: "bg-emerald-50 text-emerald-700 border-emerald-200",
  bad: "bg-red-50 text-red-700 border-red-200",
  warn: "bg-amber-50 text-amber-700 border-amber-200",
  muted: "bg-[#f1f5f9] text-[#94a3b8] border-[#e2e8f0]",
};

function timeOf(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
}

/** Who the typed number is, the pre-call checklist, and the calls made today. */
export default function DialChecks({
  phone,
  dial,
  yourName,
  todayBy = "by you",
  className = "",
}: {
  phone: string;
  dial: DialCheckState;
  /** The caller's real name; leave empty when the dial has no caller record (an owner dialling as themself). */
  yourName?: string | null;
  /** Who the "Dialled today" list covers: "by you", "by Anitha" or "by your team". */
  todayBy?: string;
  className?: string;
}) {
  const { check, loading, error, today } = dial;
  const showChecks = worthChecking(phone);
  const customer = check?.customer ?? null;

  return (
    <div className={`w-full space-y-3 ${className}`}>
      {showChecks && (
        <section className="rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-sm">
          <div className="flex items-center gap-2">
            <h3 className="min-w-0 flex-1 truncate font-label text-[10px] font-extrabold uppercase tracking-widest text-[#94a3b8]">
              Before you call · <span className="text-[#13284A]">{customer ? customer.name || formatPhone(customer.phone) : "New number"}</span>
            </h3>
            {customer?.segment && SEGMENT_WORD[customer.segment] && (
              <span className="shrink-0 rounded-full border border-[#e2e8f0] bg-[#f8fafc] px-2 py-0.5 font-label text-[9px] font-bold text-[#475569]">
                {SEGMENT_WORD[customer.segment]}
              </span>
            )}
            {customer && (
              <Link href={`/dashboard/leads/${customer.id}`} className="shrink-0 font-label text-[10px] font-bold text-primary hover:underline">
                Open customer ›
              </Link>
            )}
          </div>

          {loading ? (
            <div className="flex justify-center py-4"><Loader2 size={16} className="animate-spin text-primary" /></div>
          ) : error ? (
            <p className="mt-3 font-body text-xs leading-relaxed text-[#475569]">{error}</p>
          ) : (
            check && (
              <ul className="mt-3 space-y-2">
                {check.checks.map((row) => (
                  <li key={row.key} className="flex items-start gap-2.5">
                    <span className={`flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full border px-1 font-label text-[10px] font-bold ${TONE_CLASS[stateTone(row.state)]}`}>
                      {MARK[row.state]}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="font-body text-xs font-semibold text-[#13284A]">{row.label}</p>
                      {row.detail && <p className="font-label text-[10px] text-[#94a3b8] break-words">{row.detail}</p>}
                    </div>
                  </li>
                ))}
              </ul>
            )
          )}

          <p className="mt-3 border-t border-[#f1f5f9] pt-3 font-body text-[11px] leading-relaxed text-[#475569]">
            A number on Said stop can&apos;t be called from here.
            {yourName ? <> A new number becomes a customer with &quot;came from: dialled by {yourName}&quot;.</> : null}
            {check?.calling_from === "office" ? " Cloud calls are recorded and count in Results like any other call." : null}
          </p>
        </section>
      )}

      <section className="rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-sm">
        <h3 className="font-label text-[10px] font-extrabold uppercase tracking-widest text-[#94a3b8]">Dialled today · {todayBy}</h3>
        {today.length === 0 ? (
          <p className="mt-2 font-body text-xs text-[#94a3b8]">No calls yet today.</p>
        ) : (
          <ul className="mt-2 divide-y divide-[#f1f5f9]">
            {today.map((log) => (
              <li key={log.id} className="flex items-center gap-2 py-2">
                <span className="w-14 shrink-0 font-label text-[10px] text-[#94a3b8]">{timeOf(log.created_at)}</span>
                <span className="min-w-0 flex-1 truncate font-body text-xs font-semibold text-[#13284A]">
                  {log.leads?.name || formatPhone(log.leads?.phone) || "Unknown number"}
                </span>
                <span className="shrink-0 font-label text-[10px] text-[#475569]">{callResultLabel(callResultKey(log)) ?? "Called"}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
