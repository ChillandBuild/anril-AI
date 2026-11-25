"use client";
import { useMemo, useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { toast } from "sonner";
import { Phone } from "lucide-react";
import { coursesApi, type CoursesSummary, type FeeInstalment } from "@/lib/coursesApi";
import { cn } from "@/lib/utils";
import { Notice, errorText } from "@/app/dashboard/bookings/bookingsUi";
import { dayText, rupees } from "./coursesLogic";
import { MobileRecordCard, MobileRecordHeader } from "@/components/MobileRecord";

/** Students now · Seats left · Demo classes · Fees due this week · Waitlist. */
export function CourseTiles({ money }: { money: boolean }) {
  const { data } = useSWR<CoursesSummary>("courses/summary", coursesApi.summary, { revalidateOnFocus: false });
  if (!data) return null;
  const tiles = [
    { label: "Students now", value: String(data.students), hint: `in ${data.batches} ${data.batches === 1 ? "batch" : "batches"}` },
    { label: "Seats left", value: String(data.seats_left_this_month), hint: "in batches starting this month" },
    { label: "Demo classes", value: String(data.demo_week), hint: `this week · ${data.demo_joined} joined after` },
    {
      label: "Fees due this week",
      value: money && data.fees_due_paise != null ? rupees(data.fees_due_paise) : String(data.fees_due_students),
      hint: `${data.fees_due_students} ${data.fees_due_students === 1 ? "student" : "students"}`,
    },
    { label: "Waitlist", value: String(data.waitlist), hint: data.full_batches.length ? `${data.full_batches.join(", ")} full` : "no batch is full" },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
      {tiles.map((t) => (
        <div key={t.label} className="rounded-xl border border-[#e2e8f0] bg-white px-4 py-3">
          <p className="text-xs font-semibold text-ink-secondary">{t.label}</p>
          <p className="text-2xl font-bold tabular-nums text-ink">{t.value}</p>
          <p className="truncate text-xs text-ink-secondary">{t.hint}</p>
        </div>
      ))}
    </div>
  );
}

const STATUS: Record<FeeInstalment["status"], { label: (r: FeeInstalment) => string; cls: string }> = {
  late: { label: (r) => `${r.days_late} ${r.days_late === 1 ? "day" : "days"} late`, cls: "bg-red-50 text-red-700" },
  due_soon: { label: () => "Due soon", cls: "bg-amber-50 text-amber-800" },
  on_track: { label: () => "On track", cls: "bg-slate-100 text-slate-700" },
  paid: { label: () => "✓ Fully paid", cls: "bg-emerald-50 text-emerald-800" },
};

type Filter = "all" | "due" | "late";

/** Fee instalments: every student with a fee plan, Due this week / Late, Call and Send pay link. */
export function FeeInstalments({ canManage }: { canManage: boolean }) {
  const { data, error } = useSWR("courses/fee-instalments", coursesApi.feeInstalments, { revalidateOnFocus: false });
  const [filter, setFilter] = useState<Filter>("all");
  const [busy, setBusy] = useState<string | null>(null);
  const rows = useMemo(() => data?.rows ?? [], [data]);
  const counts = { all: rows.length, due: rows.filter((r) => r.status === "due_soon").length, late: rows.filter((r) => r.status === "late").length };
  const shown = rows.filter((r) => filter === "all" || (filter === "due" ? r.status === "due_soon" : r.status === "late"));

  async function payLink(r: FeeInstalment) {
    if (r.next_index == null) return;
    setBusy(r.plan_id);
    try {
      const { url } = await coursesApi.partPayLink(r.plan_id, r.next_index);
      const first = (r.student_name || "").trim().split(/\s+/)[0] || "there";
      const text = `Hi ${first}, your fee of ${rupees(r.next_paise)} is due${r.next_due ? ` on ${dayText(r.next_due)}` : ""}. Pay here: ${url}`;
      try { await navigator.clipboard.writeText(text); } catch { /* the WhatsApp link below still works */ }
      const digits = (r.phone || "").replace(/\D/g, "");
      toast.success("Pay link copied", digits ? { action: { label: "Open in WhatsApp", onClick: () => window.open(`https://wa.me/${digits}?text=${encodeURIComponent(text)}`, "_blank", "noopener") } } : undefined);
    } catch (err) {
      toast.error(errorText(err, "Could not make a pay link."));
    } finally {
      setBusy(null);
    }
  }

  if (error && !data) return <Notice tone="red">{errorText(error, "Could not load fee instalments.")}</Notice>;
  if (!data) return <div className="h-40 animate-pulse rounded-xl bg-surface-low" />;
  if (rows.length === 0) return <Notice>No fee plans yet. When a student joins a batch with fee parts, they show here.</Notice>;

  const chip = (f: Filter, label: string) => (
    <button type="button" aria-pressed={filter === f} onClick={() => setFilter(f)}
      className={cn("rounded-xl border px-3 py-1.5 text-sm font-semibold", filter === f ? "border-primary bg-primary text-white" : "border-[#e2e8f0] bg-white text-ink hover:bg-slate-50")}>
      {label} · {counts[f]}
    </button>
  );
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">{chip("all", "All students")}{chip("due", "Due this week")}{chip("late", "Late")}</div>
      <div className="hidden overflow-x-auto rounded-xl border border-[#e2e8f0] bg-white md:block">
        <table className="w-full min-w-[820px] text-sm">
          <thead>
            <tr className="border-b border-[#e2e8f0] bg-slate-50 text-left text-[11px] font-bold uppercase tracking-wider text-ink-secondary">
              <th className="px-4 py-2.5">Student · course</th><th className="px-3 py-2.5">Total fee</th><th className="px-3 py-2.5">Paid</th>
              <th className="px-3 py-2.5">Next due</th><th className="px-3 py-2.5">Status</th><th className="px-4 py-2.5" />
            </tr>
          </thead>
          <tbody className="divide-y divide-[#f1f5f9]">
            {shown.map((r) => (
              <tr key={r.plan_id}>
                <td className="px-4 py-2.5">
                  <p className="font-bold text-ink">{r.student_name || r.phone}</p>
                  <p className="text-xs text-ink-secondary">{[r.course_name, r.batch_name].filter(Boolean).join(" · ")}</p>
                </td>
                <td className="px-3 py-2.5 tabular-nums text-ink">{rupees(r.total_paise)} <span className="text-xs text-ink-secondary">· {r.parts} {r.parts === 1 ? "part" : "parts"}</span></td>
                <td className="px-3 py-2.5 font-bold tabular-nums text-ink">{rupees(r.paid_paise)}</td>
                <td className="px-3 py-2.5 tabular-nums text-ink">{r.next_due ? `${rupees(r.next_paise)} · ${dayText(r.next_due)}` : "—"}</td>
                <td className="px-3 py-2.5"><span className={cn("rounded-full px-2.5 py-0.5 text-xs font-bold", STATUS[r.status].cls)}>{STATUS[r.status].label(r)}</span></td>
                <td className="px-4 py-2.5">
                  <div className="flex flex-wrap justify-end gap-2">
                    {r.status === "late" && r.phone && (
                      <a href={`tel:${r.phone}`} className="inline-flex items-center gap-1 rounded-lg border border-[#e2e8f0] px-2.5 py-1 text-xs font-bold text-ink hover:bg-slate-50"><Phone size={12} /> Call</a>
                    )}
                    {r.status !== "paid" && canManage && (
                      <button type="button" disabled={busy === r.plan_id} onClick={() => void payLink(r)}
                        className="rounded-lg bg-primary px-2.5 py-1 text-xs font-bold text-white disabled:opacity-50">
                        {busy === r.plan_id ? "Making…" : "Send pay link"}
                      </button>
                    )}
                    <Link href={`/dashboard/deals/orders/${encodeURIComponent(r.deal_id)}`} className="px-1 py-1 text-xs font-bold text-primary hover:underline">
                      {r.status === "paid" ? "Receipts ›" : "Open ›"}
                    </Link>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="space-y-3 md:hidden">
        {shown.map((r) => (
          <MobileRecordCard key={r.plan_id} className="p-3">
            <MobileRecordHeader
              title={r.student_name || r.phone}
              subtitle={[r.course_name, r.batch_name].filter(Boolean).join(" · ")}
              aside={<span className={cn("rounded-full px-2.5 py-0.5 text-xs font-bold", STATUS[r.status].cls)}>{STATUS[r.status].label(r)}</span>}
            />
            <p className="mt-2 text-[13px] tabular-nums text-ink">
              Total {rupees(r.total_paise)} · {r.parts} {r.parts === 1 ? "part" : "parts"} · Paid {rupees(r.paid_paise)}
            </p>
            <p className="mt-0.5 text-[13px] tabular-nums text-ink-secondary">
              Next due: {r.next_due ? `${rupees(r.next_paise)} · ${dayText(r.next_due)}` : "—"}
            </p>
            <div className="mt-3 flex flex-wrap items-center justify-end gap-2">
              {r.status === "late" && r.phone && (
                <a href={`tel:${r.phone}`} className="inline-flex min-h-9 items-center gap-1 rounded-lg border border-[#e2e8f0] px-3 text-[13px] font-bold text-ink"><Phone size={13} /> Call</a>
              )}
              {r.status !== "paid" && canManage && (
                <button type="button" disabled={busy === r.plan_id} onClick={() => void payLink(r)}
                  className="min-h-9 rounded-lg bg-primary px-3 text-[13px] font-bold text-white disabled:opacity-50">
                  {busy === r.plan_id ? "Making…" : "Send pay link"}
                </button>
              )}
              <Link href={`/dashboard/deals/orders/${encodeURIComponent(r.deal_id)}`} className="inline-flex min-h-9 items-center px-2 text-[13px] font-bold text-primary">
                {r.status === "paid" ? "Receipts ›" : "Open ›"}
              </Link>
            </div>
          </MobileRecordCard>
        ))}
      </div>
      <p className="text-xs text-ink-secondary">Reminders go by themselves 3 days before, on the day and 3 days late when Fee reminders are on (above). Late students are worth a call.</p>
    </div>
  );
}
