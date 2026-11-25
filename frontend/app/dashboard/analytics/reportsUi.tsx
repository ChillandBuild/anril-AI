"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { Download, Printer, RefreshCw, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { AiraLoader } from "@/components/AiraLoader";
import { MobileRecordCard, MobileRecordField, MobileRecordGrid } from "@/components/MobileRecord";
import {
  deltaOf, formatValue, getPeople, leadHref, lowerIsBetter,
  type MetricKind, type PeopleRef, type PersonRow,
} from "@/lib/reportsApi";

// ─── Loading one report ───────────────────────────────────────────────────────

export interface ReportState<T> { data: T | null; err: string | null; loading: boolean; reload: () => void }

/** Runs `load` whenever `query` changes. A null query (custom dates not complete) loads nothing. */
export function useReport<T>(query: string | null, load: (query: string) => Promise<T>): ReportState<T> {
  const [data, setData] = useState<T | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const loadRef = useRef(load);
  loadRef.current = load;

  useEffect(() => {
    if (!query) {
      setData(null);
      setErr(null);
      return;
    }
    let current = true;
    setData(null);
    setErr(null);
    loadRef.current(query)
      .then((d) => { if (current) setData(d); })
      .catch((e: unknown) => { if (current) setErr(e instanceof Error ? e.message : "This report did not load. Try again."); });
    return () => { current = false; };
  }, [query, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, err, loading: !!query && !data && !err, reload };
}

// ─── Small pieces ─────────────────────────────────────────────────────────────

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-center justify-between gap-3 rounded-xl bg-red-50 p-4 font-label text-sm text-red-700 ring-1 ring-red-200">
      <span>{message}</span>
      {onRetry && (
        <button onClick={onRetry} className="shrink-0 rounded-lg bg-red-100 px-3 py-1.5 font-label text-xs font-bold text-red-700 hover:bg-red-200">
          Try again
        </button>
      )}
    </div>
  );
}

export function SectionCard({ title, hint, children, className }: { title: string; hint?: string; children: ReactNode; className?: string }) {
  return (
    <section className={cn("min-w-0 rounded-card bg-surface p-4 shadow-card ring-1 ring-[#c4c7c7]/15 sm:p-6", className)}>
      <h2 className="font-display text-base font-bold text-primary">{title}</h2>
      {hint ? <p className="mb-4 mt-1 font-label text-xs text-on-surface-muted">{hint}</p> : <div className="mb-4" />}
      {children}
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="font-label text-sm text-on-surface-muted">{children}</p>;
}

export function Loading() {
  return <AiraLoader inline className="min-h-24" />;
}

/** The one plain sentence at the top of every tab. */
export function InShort({ text }: { text?: string | null }) {
  if (!text) return null;
  return (
    <p className="rounded-xl bg-primary-50 px-4 py-3 font-body text-sm text-on-surface ring-1 ring-primary-100">
      <span className="font-bold text-primary">In short: </span>
      {text}
    </p>
  );
}

export function PlainNote({ children }: { children: ReactNode }) {
  return <p className="rounded-xl bg-amber-50 px-4 py-3 font-label text-sm text-amber-900 ring-1 ring-amber-200">{children}</p>;
}

// ─── Metric tile ──────────────────────────────────────────────────────────────

export interface MetricProps {
  label: string;
  value: number | null | undefined;
  before?: number | null;
  kind?: MetricKind;
  /** Same key the number came from; decides whether a rise is good news. */
  statKey?: string;
  people?: PeopleRef | null;
  href?: string;
  hint?: string;
  onPeople?: (ref: PeopleRef, label: string) => void;
}

export function Metric({ label, value, before, kind = "count", statKey = "", people, href, hint, onPeople }: MetricProps) {
  const delta = deltaOf(value, before, lowerIsBetter(statKey));
  const showDelta = before !== undefined && before !== null && delta.dir !== "same";
  const body = (
    <>
      <span className="block font-label text-xs font-bold text-[#556274]">{label}</span>
      <span className="mt-1 block font-display text-2xl font-extrabold text-on-surface">{formatValue(value, kind)}</span>
      {before !== undefined && before !== null ? (
        <span className="mt-1 block font-label text-xs text-[#556274]">
          {showDelta && (
            <span className={cn("mr-1 font-bold", delta.good === null ? "" : delta.good ? "text-emerald-700" : "text-red-700")}>
              {delta.dir === "up" ? "▲" : "▼"} {delta.pct === null ? "" : `${Math.abs(delta.pct)}%`}
            </span>
          )}
          before: {formatValue(before, kind)}
        </span>
      ) : null}
      {hint ? <span className="mt-1 block font-label text-xs text-[#556274]">{hint}</span> : null}
    </>
  );
  const box = "block w-full rounded-card bg-surface p-4 text-left shadow-card ring-1 ring-[#c4c7c7]/15";
  const clickable = `${box} transition-colors hover:ring-primary-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300`;
  if (people && onPeople && (value ?? 0) > 0) {
    return (
      <button type="button" className={clickable} onClick={() => onPeople(people, label)} aria-label={`${label}: ${formatValue(value, kind)}. Show the people`}>
        {body}
      </button>
    );
  }
  if (href) return <Link href={href} className={clickable}>{body}</Link>;
  return <div className={box}>{body}</div>;
}

export function MetricGrid({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-4">{children}</div>;
}

// ─── Table ────────────────────────────────────────────────────────────────────

export interface Column<R> { key: string; label: string; right?: boolean; render: (row: R) => ReactNode }

export function DataTable<R>({ columns, rows, rowKey, empty }: { columns: Column<R>[]; rows: R[]; rowKey: (row: R, i: number) => string; empty: string }) {
  if (rows.length === 0) return <Empty>{empty}</Empty>;
  return (
    <>
    <div className="space-y-3 md:hidden">
      {rows.map((row, i) => (
        <PhoneRow key={rowKey(row, i)} columns={columns} row={row} />
      ))}
    </div>
    <div className="hidden overflow-x-auto md:block">
      <table className="w-full text-left">
        <thead>
          <tr className="border-b border-surface-mid">
            {columns.map((c) => (
              <th key={c.key} scope="col" className={cn("whitespace-nowrap pb-3 pr-4 font-label text-xs font-semibold uppercase tracking-wider text-[#556274]", c.right && "text-right")}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={rowKey(row, i)} className="border-b border-surface-mid/50">
              {columns.map((c) => (
                <td key={c.key} className={cn("py-3 pr-4 font-label text-sm text-on-surface", c.right && "text-right")}>{c.render(row)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
    </>
  );
}

const PHONE_PAIRS = 6;

/** Phone card for one DataTable row: first column is the title, the rest are label/value tiles. */
function PhoneRow<R>({ columns, row }: { columns: Column<R>[]; row: R }) {
  const [more, setMore] = useState(false);
  const [first, ...rest] = columns;
  const shown = more ? rest : rest.slice(0, PHONE_PAIRS);
  return (
    <MobileRecordCard className="p-3">
      <div className="min-w-0 break-words font-body text-sm font-bold text-on-surface">{first.render(row)}</div>
      {shown.length > 0 && (
        <MobileRecordGrid className="mt-3">
          {shown.map((c) => (
            <MobileRecordField key={c.key} label={c.label} value={c.render(row)} />
          ))}
        </MobileRecordGrid>
      )}
      {rest.length > PHONE_PAIRS && (
        <button
          type="button"
          onClick={() => setMore((m) => !m)}
          aria-expanded={more}
          className="mt-3 min-h-9 w-full rounded-xl border border-surface-mid text-[13px] font-semibold text-on-surface-muted"
        >
          {more ? "Less" : `More (${rest.length - PHONE_PAIRS})`}
        </button>
      )}
    </MobileRecordCard>
  );
}

/** A number inside a table that opens the people behind it. */
export function PeopleNumber({ value, onClick, label }: { value: number | null | undefined; onClick?: () => void; label: string }) {
  const text = (value ?? 0).toLocaleString("en-IN");
  if (!onClick || !value) return <span>{text}</span>;
  return (
    <button type="button" onClick={onClick} aria-label={`${label}: ${text}. Show the people`} className="font-bold text-primary underline decoration-dotted underline-offset-4 hover:text-primary-700">
      {text}
    </button>
  );
}

// ─── Buttons row: refresh, download, print ────────────────────────────────────

const BTN = "flex items-center justify-center gap-2 rounded-xl border border-[#e2e8f0] bg-white px-3 py-2 font-label text-xs font-bold text-[#0A1528] shadow-sm transition-colors hover:bg-[#f1f5f9] disabled:opacity-40";

export function ReportActions({ onReload, onDownload, downloadLabel = "Download", busy }: { onReload: () => void; onDownload?: () => void; downloadLabel?: string; busy?: boolean }) {
  return (
    <div data-print-hide className="flex flex-wrap gap-2">
      <button type="button" onClick={onReload} className={BTN}>
        <RefreshCw size={12} className={busy ? "animate-spin" : ""} /> Refresh
      </button>
      {onDownload && (
        <button type="button" onClick={onDownload} className={BTN}>
          <Download size={12} /> {downloadLabel}
        </button>
      )}
      <button type="button" onClick={() => window.print()} className={BTN}>
        <Printer size={12} /> Print / Save as PDF
      </button>
    </div>
  );
}

// ─── People side sheet ────────────────────────────────────────────────────────

export interface PeopleRequest { ref: PeopleRef; title: string }

export function PeopleSheet({ request, query, onClose }: { request: PeopleRequest | null; query: string | null; onClose: () => void }) {
  const [rows, setRows] = useState<PersonRow[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!request || !query) return;
    let current = true;
    setRows(null);
    setErr(null);
    getPeople(request.ref.metric, query, request.ref.id)
      .then((r) => { if (current) setRows(r); })
      .catch((e: unknown) => { if (current) setErr(e instanceof Error ? e.message : "The list did not load. Try again."); });
    return () => { current = false; };
  }, [request, query]);

  useEffect(() => {
    if (!request) return;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [request, onClose]);

  if (!request) return null;
  return (
    <div data-print-hide className="fixed inset-0 z-dialog flex justify-end">
      <button type="button" aria-label="Close" className="absolute inset-0 bg-black/30" onClick={onClose} tabIndex={-1} />
      <aside role="dialog" aria-modal="true" aria-label={request.title} className="relative flex h-full w-full max-w-md flex-col bg-white shadow-2xl">
        <div className="flex items-start justify-between gap-3 border-b border-surface-mid p-4">
          <div className="min-w-0">
            <h2 className="font-display text-base font-bold text-primary">{request.title}</h2>
            <p className="font-label text-xs text-[#556274]">{rows ? `${rows.length.toLocaleString("en-IN")}${rows.length >= 500 ? "+" : ""} people. Tap one to open their page.` : "Loading…"}</p>
          </div>
          <button ref={closeRef} type="button" onClick={onClose} aria-label="Close" className="rounded-lg p-2 text-[#556274] hover:bg-surface-low">
            <X size={18} />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          {err && <div className="p-2"><ErrorBox message={err} /></div>}
          {!rows && !err && <Loading />}
          {rows && rows.length === 0 && <div className="p-3"><Empty>Nobody to show for this number.</Empty></div>}
          {rows && rows.map((p) => (
            <Link key={p.lead_id} href={leadHref(p.lead_id)} className="block rounded-xl px-3 py-2.5 hover:bg-surface-low">
              <span className="block font-body text-sm font-semibold text-on-surface">{p.name || p.phone || "No name"}</span>
              <span className="block font-label text-xs text-[#556274]">{[p.name ? p.phone : null, p.detail].filter(Boolean).join(" · ")}</span>
            </Link>
          ))}
        </div>
      </aside>
    </div>
  );
}

/** Hook the tabs share: which number's people are open. */
export function usePeopleSheet() {
  const [request, setRequest] = useState<PeopleRequest | null>(null);
  const open = useCallback((ref: PeopleRef, title: string) => setRequest({ ref, title }), []);
  const close = useCallback(() => setRequest(null), []);
  return { request, open, close };
}
