"use client";
import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, Download, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { API_URL, api, getAuthHeaders } from "@/lib/api";
import type { WaFormResponseRow } from "@/lib/api";
import { cn } from "@/lib/utils";
import { AiraLoader } from "@/components/AiraLoader";
import { useWhatsappForm, useWhatsappFormResponses } from "@/hooks/useApi";
import { CatalogueTabs } from "../../../catalog/CatalogueTabs";
import { SectionLoadGate } from "../../../settings/SettingsSection";

const PAGE_SIZE = 50;

const OUTCOME: Record<WaFormResponseRow["outcome"], { label: string; cls: string }> = {
  saved: { label: "Saved", cls: "bg-emerald-50 text-emerald-700" },
  link_sent: { label: "Payment link sent", cls: "bg-emerald-50 text-emerald-700" },
  continued_in_chat: { label: "Continued in chat", cls: "bg-blue-50 text-blue-700" },
  received: { label: "Received", cls: "bg-surface-mid text-ink-secondary" },
  rejected: { label: "Not verified", cls: "bg-amber-50 text-amber-800" },
};

function when(iso: string) {
  return new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit", timeZone: "Asia/Kolkata" });
}

export default function FormAnswersPage() {
  const { id } = useParams<{ id: string }>();
  const isServices = id === "services";
  const { data: design } = useWhatsappForm(isServices ? null : id);
  const [page, setPage] = useState(1);
  const { data, error, mutate } = useWhatsappFormResponses(id, page);
  const [downloading, setDownloading] = useState(false);
  const title = isServices ? "Services form" : design?.name ?? "Form";

  async function download() {
    setDownloading(true);
    try {
      const res = await fetch(`${API_URL}${api.whatsappForms.responsesCsvPath(id)}`, { headers: await getAuthHeaders() });
      if (!res.ok) throw new Error("Couldn't download the answers. Try again.");
      const url = URL.createObjectURL(await res.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = `${title.replace(/[\/:*?"<>|]/g, "_")}_answers.csv`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't download the answers.");
    } finally {
      setDownloading(false);
    }
  }

  const total = data?.total ?? 0;
  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="w-full space-y-5 pb-28">
      <CatalogueTabs />
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <Link href={isServices ? "/dashboard/forms" : `/dashboard/forms/${id}`} className="inline-flex items-center gap-1.5 font-label text-xs font-semibold text-ink-secondary hover:text-ink">
            <ArrowLeft size={14} /> {isServices ? "All forms" : "Back to the form"}
          </Link>
          <h2 className="truncate font-display text-lg font-bold text-ink">{title} · answers</h2>
          <p className="font-body text-xs text-ink-muted tabular-nums">{total} submitted</p>
        </div>
        <button
          type="button"
          onClick={download}
          disabled={downloading || total === 0}
          className="inline-flex items-center gap-1.5 rounded-xl px-3 py-2 font-label text-xs font-semibold text-ink ring-1 ring-surface-mid hover:bg-surface-low disabled:opacity-40"
        >
          {downloading ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />} Download CSV
        </button>
      </div>

      {error ? (
        <SectionLoadGate state="error" onRetry={() => mutate()}>{null}</SectionLoadGate>
      ) : !data ? (
        <AiraLoader inline className="min-h-[40vh]" />
      ) : data.data.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-surface-mid px-6 py-12 text-center">
          <p className="font-label text-sm font-semibold text-ink">No answers yet</p>
          <p className="mt-1 font-body text-xs text-ink-secondary">They show here as soon as someone submits the form on WhatsApp.</p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-2xl bg-surface ring-1 ring-surface-mid">
          <table className="w-full min-w-[640px] text-left">
            <thead className="border-b border-surface-mid bg-surface-low">
              <tr>
                {["Submitted", "Customer", ...data.columns, "Offers", "Result"].map((col) => (
                  <th key={col} className="whitespace-nowrap px-4 py-2.5 font-label text-[11px] font-semibold uppercase tracking-wider text-ink-muted">{col}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-mid">
              {data.data.map((row) => (
                <tr key={row.id} className="align-top hover:bg-surface-low/60">
                  <td className="whitespace-nowrap px-4 py-3 font-body text-xs text-ink-muted">{when(row.submitted_at)}</td>
                  <td className="px-4 py-3">
                    <p className="max-w-[180px] truncate font-label text-xs font-semibold text-ink">{row.name || "—"}</p>
                    <p className="font-body text-[11px] text-ink-muted tabular-nums">{row.phone || ""}</p>
                  </td>
                  {data.columns.map((col) => (
                    <td key={col} className="max-w-[220px] px-4 py-3 font-body text-xs text-ink" title={row.answers[col] ?? ""}>
                      <span className="line-clamp-3 break-words">{row.answers[col] || "—"}</span>
                    </td>
                  ))}
                  <td className="whitespace-nowrap px-4 py-3 font-body text-xs text-ink-secondary">{row.offers ? "Yes" : "No"}</td>
                  <td className="whitespace-nowrap px-4 py-3">
                    <span className={cn("rounded-full px-2 py-0.5 font-label text-[11px] font-semibold", OUTCOME[row.outcome].cls)}>
                      {OUTCOME[row.outcome].label}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {lastPage > 1 && (
        <div className="flex items-center justify-end gap-2">
          <button type="button" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1}
            className="rounded-lg px-3 py-1.5 font-label text-xs font-semibold ring-1 ring-surface-mid disabled:opacity-40">Previous</button>
          <span className="font-body text-xs text-ink-muted tabular-nums">{page} / {lastPage}</span>
          <button type="button" onClick={() => setPage((p) => Math.min(lastPage, p + 1))} disabled={page === lastPage}
            className="rounded-lg px-3 py-1.5 font-label text-xs font-semibold ring-1 ring-surface-mid disabled:opacity-40">Next</button>
        </div>
      )}
    </div>
  );
}
