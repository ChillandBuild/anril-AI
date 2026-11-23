"use client";
import Link from "next/link";
import { SwitchPill } from "@/components/ui/controls";
import { statusWords, type AutomationRow } from "@/lib/automationsApi";

export function AutomationLine({ row, canManage, busy, onToggle }: { row: AutomationRow; canManage: boolean; busy: boolean; onToggle: (row: AutomationRow, on: boolean) => void }) {
  const paused = row.paused || !!row.paused_reason;
  return (
    <li className="rounded-2xl border border-border-subtle bg-surface-subtle p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Link href={row.href} className="font-body text-sm font-bold text-ink underline-offset-2 hover:underline">{row.name}</Link>
          {row.template_name && (
            <p className="mt-0.5 font-body text-xs text-[#556274]">
              Message: {row.template_name}
              {row.template_status ? ` · ${statusWords(row.template_status)}` : ""}
            </p>
          )}
          {row.note && <p className="mt-0.5 font-body text-xs text-[#556274]">{row.note}</p>}
          {paused && (
            <p className="mt-1 inline-block rounded-full bg-red-50 px-2 py-0.5 font-label text-xs font-bold text-red-800">
              Paused{row.paused_reason ? `: ${row.paused_reason}` : ""}
            </p>
          )}
        </div>
        {row.switchable !== false ? (
          <SwitchPill on={row.on} disabled={!canManage} loading={busy} aria-label={row.name} onChange={(next) => onToggle(row, next)} />
        ) : (
          <span className="font-body text-xs text-[#556274]">{row.on ? "On" : "Off"}</span>
        )}
      </div>
    </li>
  );
}
