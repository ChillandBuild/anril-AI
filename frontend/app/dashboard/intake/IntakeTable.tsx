"use client";
import { useEffect, useRef } from "react";
import { Select } from "@/components/ui/Select";
import { IntakeSession } from "@/lib/api";
import { FieldColumn } from "./columns";

const STATUS_BADGE: Record<string, string> = {
  awaiting_payment: "bg-amber-50 text-amber-700 border-amber-200",
  paid: "bg-emerald-50 text-emerald-700 border-emerald-200",
  resolved: "bg-slate-50 text-slate-500 border-slate-200",
};

const STATUS_LABEL: Record<string, string> = {
  awaiting_payment: "Awaiting payment",
  paid: "Paid",
  resolved: "Resolved",
};

interface PackageOption {
  key: string;
  name: string;
  amount_paise: number;
}

interface IntakeTableProps {
  rows: IntakeSession[];
  columns: FieldColumn[];
  visibleKeys: Set<string>;
  packages: PackageOption[];
  hasMore: boolean;
  loadingMore: boolean;
  onLoadMore: () => void;
  onChangePackage: (sessionId: string, packageKey: string) => void;
}

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

/** Dates are stored as 2003-11-19; staff read day-first, so show 19-11-2003. */
function formatAnswer(value: string | undefined): string {
  if (!value) return "—";
  const iso = ISO_DATE.exec(value);
  return iso ? `${iso[3]}-${iso[2]}-${iso[1]}` : value;
}

function PackageCell({
  row, packages, onChangePackage,
}: {
  row: IntakeSession;
  packages: PackageOption[];
  onChangePackage: (sessionId: string, packageKey: string) => void;
}) {
  const canEdit = row.status === "awaiting_payment" && packages.length > 1;

  // The picker is shown directly (no pencil step): a closed menu has no blur event to cancel an "editing" mode.
  if (canEdit) {
    return (
      // Stop clicks (also from the floating menu) from reaching the row's own click handler.
      <span onClick={(e) => e.stopPropagation()}>
        <Select
          size="sm"
          aria-label="Change package"
          className="w-auto min-w-[160px]"
          value={row.package_key ?? ""}
          onChange={(key) => onChangePackage(row.id, key)}
          placeholder={row.package_name || "Choose package"}
          options={packages.map((p) => ({ value: p.key, label: `${p.name} — ₹${(p.amount_paise / 100).toFixed(0)}` }))}
        />
      </span>
    );
  }

  return <span className="inline-flex items-center gap-1.5">{row.package_name || "—"}</span>;
}

export function IntakeTable({
  rows, columns, visibleKeys, packages, hasMore, loadingMore, onLoadMore, onChangePackage,
}: IntakeTableProps) {
  const sentinel = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const node = sentinel.current;
    if (!node || !hasMore) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && !loadingMore) onLoadMore();
      },
      { rootMargin: "200px" }
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [hasMore, loadingMore, onLoadMore]);

  const shown = columns.filter((c) => visibleKeys.has(c.key));

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="border-b border-border bg-surface-subtle">
            <th className="sticky left-0 z-20 w-[180px] min-w-[180px] max-w-[180px] bg-surface-subtle px-4 py-2 font-label text-[10px] font-bold uppercase tracking-wide text-ink-muted">
              Lead
            </th>
            <th className="sticky left-[180px] z-20 w-[140px] min-w-[140px] max-w-[140px] border-r border-border bg-surface-subtle px-4 py-2 font-label text-[10px] font-bold uppercase tracking-wide text-ink-muted shadow-[inset_-1px_0_0_0_#e2e8f0]">
              Phone
            </th>
            <th className="whitespace-nowrap px-4 py-2 font-label text-[10px] font-bold uppercase tracking-wide text-ink-muted">Status</th>
            <th className="whitespace-nowrap px-4 py-2 font-label text-[10px] font-bold uppercase tracking-wide text-ink-muted">Deal</th>
            <th className="whitespace-nowrap px-4 py-2 font-label text-[10px] font-bold uppercase tracking-wide text-ink-muted">Package</th>
            <th className="whitespace-nowrap px-4 py-2 font-label text-[10px] font-bold uppercase tracking-wide text-ink-muted">Amount</th>
            <th className="whitespace-nowrap px-4 py-2 font-label text-[10px] font-bold uppercase tracking-wide text-ink-muted">Submitted</th>
            {shown.map((col) => (
              <th key={col.key} className="whitespace-nowrap px-4 py-2 font-label text-[10px] font-bold uppercase tracking-wide text-ink-muted">
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const leadName = row.leads?.name || row.collected_data?.name || "Unknown lead";
            const leadPhone = row.leads?.phone || "—";
            return (
              <tr key={row.id} className="group border-b border-border-subtle hover:bg-surface-subtle">
                <td
                  title={leadName}
                  className="sticky left-0 z-10 w-[180px] min-w-[180px] max-w-[180px] bg-surface px-4 py-3 font-label text-sm font-semibold text-ink group-hover:bg-surface-subtle"
                >
                  <div className="truncate" title={leadName}>
                    {leadName}
                  </div>
                </td>
                <td
                  title={leadPhone}
                  className="sticky left-[180px] z-10 w-[140px] min-w-[140px] max-w-[140px] whitespace-nowrap border-r border-border bg-surface px-4 py-3 font-body text-sm text-ink-muted shadow-[inset_-1px_0_0_0_#e2e8f0] group-hover:bg-surface-subtle"
                >
                  <div className="truncate" title={leadPhone}>
                    {leadPhone}
                  </div>
                </td>
                <td className="whitespace-nowrap px-4 py-3">
                  <span className={`inline-flex rounded-full border px-2.5 py-1 font-label text-[10px] font-bold ${STATUS_BADGE[row.status]}`}>
                    {STATUS_LABEL[row.status]}
                  </span>
                </td>
                <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-ink-secondary">
                  {row.deal_label || <span className="text-ink-muted">Not yet</span>}
                </td>
                <td className="whitespace-nowrap px-4 py-3 font-body text-sm text-ink">
                  <PackageCell row={row} packages={packages} onChangePackage={onChangePackage} />
                </td>
                <td className="whitespace-nowrap px-4 py-3 font-body text-sm text-ink">
                  {row.amount_paise ? `₹${(row.amount_paise / 100).toFixed(0)}` : "—"}
                  {row.amount_mismatch && (
                    <span className="ml-1 font-label text-[10px] font-bold text-amber-700" title="Amount paid differs from the package price">
                      ⚠
                    </span>
                  )}
                  {!!row.gst_amount_paise && row.gst_amount_paise > 0 && (
                    <div className="font-body text-[11px] text-ink-muted">
                      (incl. ₹{(row.gst_amount_paise / 100).toFixed(2)} GST)
                    </div>
                  )}
                </td>
                <td className="whitespace-nowrap px-4 py-3 font-body text-sm text-ink-muted">
                  {new Date(row.created_at).toLocaleDateString()}
                </td>
                {shown.map((col) => (
                  <td key={col.key} className="whitespace-nowrap px-4 py-3 font-body text-sm text-ink">
                    {formatAnswer(row.collected_data?.[col.key])}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
      <div ref={sentinel} className="h-8" />
      {loadingMore && (
        <p className="py-3 text-center font-body text-xs text-ink-muted">Loading more…</p>
      )}
    </div>
  );
}
