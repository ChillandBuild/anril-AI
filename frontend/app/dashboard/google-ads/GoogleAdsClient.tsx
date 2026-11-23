"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Lock, Pencil } from "lucide-react";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { googleAdsApi } from "@/lib/googleAdsApi";
import type { GoogleAdsReport, GoogleAdsRow } from "@/lib/googleAdsApi";
import { NewLinkCard } from "./NewLinkCard";
import { SpendEditor } from "./SpendEditor";
import { UploadCard } from "./UploadCard";
import { countCell, currentMonthIst, formatRupees, monthLabel, paidCell, shiftMonth } from "./googleAdsLogic";

const CALLS_HINT = "Calls your team made or got from these customers";
const CALLS_HINT_SHORT = "your team's calls with them";

export function GoogleAdsClient() {
  const { role, permissions, loading: roleLoading } = useAuthRole();
  const canView = role === "owner" || permissions.includes("meta_ads.view") || permissions.includes("meta_ads.manage");
  const canManage = role === "owner" || permissions.includes("meta_ads.manage");

  const [month, setMonth] = useState(currentMonthIst());
  const [report, setReport] = useState<GoogleAdsReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<string | null>(null);

  // Only the newest request may fill the page: month clicks can overlap, and a slow answer for an
  // older month must not replace the month being shown.
  const latest = useRef(0);
  const load = useCallback(async () => {
    const id = ++latest.current;
    setError(null);
    setLoading(true);
    try {
      const res = await googleAdsApi.campaigns(month);
      if (id !== latest.current || res.month !== month) return;
      setReport(res);
    } catch (err) {
      if (id !== latest.current) return;
      setError(err instanceof Error ? err.message : "Could not load Google Ads");
    } finally {
      if (id === latest.current) setLoading(false);
    }
  }, [month]);

  useEffect(() => {
    if (roleLoading || !canView) return;
    setEditing(null);
    void load();
  }, [load, roleLoading, canView]);

  if (!roleLoading && !canView) {
    return <p className="p-6 text-sm text-on-surface-muted">You do not have access to Google Ads.</p>;
  }

  // A report for another month stays on screen while the new one loads, so editing is off until it lands.
  const showMoney = report ? report.totals.spent_paise !== undefined : false;
  const busy = loading || report?.month !== month;
  const rows = report?.rows ?? [];
  const isCurrent = month === currentMonthIst();

  return (
    <div className="mx-auto max-w-5xl space-y-4 pb-10">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-display text-xl font-black text-on-surface">Google Ads</h1>
        <div className="flex items-center gap-1" role="group" aria-label="Month">
          <button type="button" aria-label="Previous month" onClick={() => setMonth(shiftMonth(month, -1))}
            className="rounded-lg border border-surface-mid p-2 text-on-surface">
            <ChevronLeft size={16} aria-hidden />
          </button>
          <span className="min-w-[9rem] text-center text-sm font-bold text-on-surface" aria-live="polite">{monthLabel(month)}</span>
          <button type="button" aria-label="Next month" disabled={isCurrent} onClick={() => setMonth(shiftMonth(month, 1))}
            className="rounded-lg border border-surface-mid p-2 text-on-surface disabled:opacity-30">
            <ChevronRight size={16} aria-hidden />
          </button>
        </div>
      </header>

      {error && (
        <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-700">
          {error}{" "}
          <button type="button" onClick={() => void load()} className="font-bold underline">Try again</button>
        </p>
      )}

      <section aria-label="Campaigns" className="card rounded-2xl p-2 sm:p-4">
        {loading && !report ? (
          <p className="p-4 text-sm text-on-surface-muted">Loading…</p>
        ) : rows.length === 0 ? (
          <p className="p-4 text-sm text-on-surface-muted">
            No Google campaigns yet. Make a tracked link below and use it in a Google ad.
          </p>
        ) : (
          <>
            <DesktopTable report={report!} showMoney={showMoney} canEdit={canManage && showMoney} busy={busy} editing={editing} setEditing={setEditing} month={month} reload={load} />
            <PhoneCards report={report!} showMoney={showMoney} canEdit={canManage && showMoney} busy={busy} editing={editing} setEditing={setEditing} month={month} reload={load} />
            <p className="mt-2 px-2 text-xs text-on-surface-muted">
              Chats, hot and paid are for customers whose first chat started in {monthLabel(month)}. Calls are this month&apos;s calls with
              customers whose first chat started this month. &quot;—&quot; means no spend report for this month yet.
            </p>
          </>
        )}
      </section>

      {canManage && (
        <>
          <NewLinkCard onCreated={() => void load()} />
          <UploadCard month={month} campaigns={rows} showMoney={showMoney} onChanged={() => void load()} />
        </>
      )}

      <section
        aria-label="Connect Google Ads account"
        className="flex items-start gap-3 rounded-2xl border border-dashed border-surface-mid bg-surface-low p-4 opacity-70"
      >
        <Lock size={18} className="mt-0.5 shrink-0 text-on-surface-muted" aria-hidden />
        <div>
          <p className="text-sm font-bold text-on-surface-muted">Connect Google Ads account</p>
          <p className="text-sm text-on-surface-muted">Coming soon: needs Google approval. Until then, upload the report above.</p>
        </div>
      </section>
    </div>
  );
}

type TableProps = {
  report: GoogleAdsReport;
  showMoney: boolean;
  canEdit: boolean;
  busy: boolean;
  editing: string | null;
  setEditing: (id: string | null) => void;
  month: string;
  reload: () => Promise<void>;
};

function perChat(row: { per_chat_paise?: number | null }, showMoney: boolean) {
  return showMoney ? formatRupees(row.per_chat_paise) : null;
}

function DesktopTable({ report, showMoney, canEdit, busy, editing, setEditing, month, reload }: TableProps) {
  const th = "px-3 py-2 text-xs font-bold uppercase tracking-wide text-on-surface-muted";
  const td = "px-3 py-2.5 text-sm text-on-surface tabular-nums text-right";
  return (
    <div className="hidden overflow-x-auto md:block">
      <table className="w-full">
        <thead>
          <tr className="border-b border-surface-mid">
            <th scope="col" className={`${th} text-left`}>Campaign</th>
            {showMoney && <th scope="col" className={`${th} text-right`}>Spent</th>}
            <th scope="col" className={`${th} text-right`}>Clicks</th>
            <th scope="col" className={`${th} text-right`}>Chats</th>
            <th scope="col" className={`${th} text-right`} title={CALLS_HINT}>Calls</th>
            <th scope="col" className={`${th} text-right`}>Hot</th>
            <th scope="col" className={`${th} text-right`}>Paid</th>
            {showMoney && <th scope="col" className={`${th} text-right`}>Per chat</th>}
            {canEdit && <th scope="col" className="w-10"><span className="sr-only">Edit</span></th>}
          </tr>
        </thead>
        <tbody>
          {report.rows.map((row) => (
            <RowGroup key={row.campaign_id} row={row} showMoney={showMoney} canEdit={canEdit} busy={busy} editing={editing} setEditing={setEditing} month={month} reload={reload} td={td} />
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t border-surface-mid font-bold">
            <th scope="row" className="px-3 py-2.5 text-left text-sm">Total</th>
            {showMoney && <td className={td}>{formatRupees(report.totals.spent_paise)}</td>}
            <td className={td}>{countCell(report.totals.clicks)}</td>
            <td className={td}>{countCell(report.totals.chats)}</td>
            <td className={td}>{countCell(report.totals.calls)}</td>
            <td className={td}>{countCell(report.totals.hot)}</td>
            <td className={td}>{paidCell(report.totals.paid_orders, report.totals.paid_paise)}</td>
            {showMoney && <td className={td}>{perChat(report.totals, showMoney)}</td>}
            {canEdit && <td />}
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

function RowGroup({ row, showMoney, canEdit, busy, editing, setEditing, month, reload, td }: Omit<TableProps, "report"> & { row: GoogleAdsRow; td: string }) {
  const open = editing === row.campaign_id;
  const cols = 6 + (showMoney ? 2 : 0) + (canEdit ? 1 : 0);
  return (
    <>
      <tr className="border-b border-surface-mid/60">
        <th scope="row" className="px-3 py-2.5 text-left text-sm font-bold text-on-surface">{row.name}</th>
        {showMoney && <td className={td}>{formatRupees(row.spent_paise)}</td>}
        <td className={td}>{countCell(row.clicks)}</td>
        <td className={td}>{countCell(row.chats)}</td>
        <td className={td}>{countCell(row.calls)}</td>
        <td className={td}>{countCell(row.hot)}</td>
        <td className={td}>{paidCell(row.paid_orders, row.paid_paise)}</td>
        {showMoney && <td className={td}>{perChat(row, showMoney)}</td>}
        {canEdit && (
          <td className="px-1">
            <button type="button" aria-label={`Edit spend for ${row.name}`} disabled={busy} onClick={() => setEditing(open ? null : row.campaign_id)}
              className="rounded-lg p-2 text-on-surface-muted hover:text-primary disabled:opacity-30">
              <Pencil size={14} aria-hidden />
            </button>
          </td>
        )}
      </tr>
      {open && (
        <tr>
          <td colSpan={cols} className="p-2">
            <SpendEditor row={row} month={month} onCancel={() => setEditing(null)} onSaved={() => { setEditing(null); void reload(); }} />
          </td>
        </tr>
      )}
    </>
  );
}

function PhoneCards({ report, showMoney, canEdit, busy, editing, setEditing, month, reload }: TableProps) {
  const stat = (label: string, value: string, hint?: string) => (
    <div>
      <dt className="text-xs text-on-surface-muted">{label}</dt>
      {hint && <dd className="text-xs leading-tight text-on-surface-muted">{hint}</dd>}
      <dd className="text-sm font-bold text-on-surface tabular-nums">{value}</dd>
    </div>
  );
  return (
    <ul className="space-y-2 md:hidden">
      {report.rows.map((row) => (
        <li key={row.campaign_id} className="rounded-xl border border-surface-mid p-3">
          <div className="flex items-start justify-between gap-2">
            <p className="min-w-0 break-words text-sm font-bold text-on-surface">{row.name}</p>
            {canEdit && (
              <button type="button" aria-label={`Edit spend for ${row.name}`} disabled={busy} onClick={() => setEditing(editing === row.campaign_id ? null : row.campaign_id)}
                className="shrink-0 rounded-lg p-2 text-on-surface-muted disabled:opacity-30">
                <Pencil size={14} aria-hidden />
              </button>
            )}
          </div>
          <dl className="mt-2 grid grid-cols-3 gap-x-3 gap-y-2">
            {showMoney && stat("Spent", formatRupees(row.spent_paise))}
            {stat("Clicks", countCell(row.clicks))}
            {stat("Chats", countCell(row.chats))}
            {stat("Calls", countCell(row.calls), CALLS_HINT_SHORT)}
            {stat("Hot", countCell(row.hot))}
            {stat("Paid", paidCell(row.paid_orders, row.paid_paise))}
            {showMoney && stat("Per chat", formatRupees(row.per_chat_paise))}
          </dl>
          {editing === row.campaign_id && (
            <div className="mt-2">
              <SpendEditor row={row} month={month} onCancel={() => setEditing(null)} onSaved={() => { setEditing(null); void reload(); }} />
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}
