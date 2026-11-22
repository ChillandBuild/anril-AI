"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { api, type AutoMessageSentRow } from "@/lib/api";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { formatWhen, ghostBtn, focusRing, tapArea } from "../shared";
import { RANGES, SENT_STATUS, notSentBanner } from "./sentText";

const PAGE = 50;
const TH = "px-3 py-2 text-left sm:px-4 font-label text-xs font-bold uppercase tracking-wide text-ink-secondary";

function Pill({ status }: { status: AutoMessageSentRow["status"] }) {
  const s = SENT_STATUS[status];
  return <span className={`whitespace-nowrap rounded-full border px-2.5 py-0.5 font-label text-xs font-bold ${s.cls}`}>{s.label}</span>;
}

function Action({ row }: { row: AutoMessageSentRow }) {
  const { label, href } = row.action;
  if (!href) return <span className="font-body text-xs text-ink-secondary">{label}</span>;
  return (
    <Link href={href} className={`inline-flex items-center font-body text-xs font-semibold text-primary underline-offset-2 hover:underline ${focusRing} ${tapArea}`}>
      {label} ›
    </Link>
  );
}

function Who({ row }: { row: AutoMessageSentRow }) {
  return row.name ? (
    <>
      <p className="break-words font-semibold text-ink">{row.name}</p>
      <p className="truncate whitespace-nowrap text-xs text-ink-secondary" title={row.phone ?? undefined}>{row.phone}</p>
    </>
  ) : (
    <p className="truncate whitespace-nowrap font-semibold text-ink" title={row.phone ?? undefined}>{row.phone ?? "Unknown"}</p>
  );
}

export default function SentPage() {
  const { role, permissions, loading } = useAuthRole();
  const canView = role === "owner" || permissions.includes("auto_messages.view") || permissions.includes("auto_messages.manage");

  const [days, setDays] = useState<7 | 30>(7);
  const [onlyNotSent, setOnlyNotSent] = useState(false);
  const [rows, setRows] = useState<AutoMessageSentRow[] | null>(null);
  const [todayNotSent, setTodayNotSent] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState<"load" | "more" | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  // Only the newest request may write to the list (filters can change while one is in flight).
  const requestId = useRef(0);

  const loadFirst = useCallback(async () => {
    const id = ++requestId.current;
    setRows(null);
    setError(null);
    try {
      const page = await api.autoMessages.sent({ days, onlyNotSent, limit: PAGE, offset: 0 });
      if (id !== requestId.current) return;
      setRows(page.rows);
      setTodayNotSent(page.today_not_sent);
      setHasMore(page.has_more);
    } catch {
      if (id === requestId.current) setError("load");
    }
  }, [days, onlyNotSent]);

  useEffect(() => {
    if (!loading && canView) void loadFirst();
  }, [loading, canView, loadFirst]);

  async function showMore() {
    if (!rows) return;
    const id = requestId.current;
    setLoadingMore(true);
    setError(null);
    try {
      const page = await api.autoMessages.sent({ days, onlyNotSent, limit: PAGE, offset: rows.length });
      if (id !== requestId.current) return;
      setRows((prev) => [...(prev ?? []), ...page.rows]);
      setHasMore(page.has_more);
    } catch {
      if (id === requestId.current) setError("more");
    } finally {
      setLoadingMore(false);
    }
  }

  if (loading) return <div className="m-6 min-h-[320px] animate-pulse rounded-2xl bg-border-subtle" />;
  if (!canView) {
    return (
      <div className="py-20 text-center">
        <p className="font-body text-sm text-ink-secondary">You do not have access to Auto-Messages.</p>
      </div>
    );
  }

  const chip = (on: boolean) =>
    `rounded-full border px-3 py-1.5 font-label text-xs font-semibold transition ${focusRing} ${tapArea} ${
      on ? "border-primary bg-primary text-white" : "border-border bg-white text-ink-secondary hover:border-primary/40"
    }`;

  return (
    <div className="mx-auto w-full max-w-5xl space-y-4 px-4 py-6 sm:px-6">
      {todayNotSent > 0 && (
        <div role="status" className="flex items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-700" aria-hidden />
          <p className="font-body text-sm text-amber-900">{notSentBanner(todayNotSent)}</p>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-2" role="group" aria-label="Time range">
          {RANGES.map((r) => (
            <button key={r.days} type="button" aria-pressed={days === r.days} onClick={() => setDays(r.days)} className={chip(days === r.days)}>
              {r.label}
            </button>
          ))}
        </div>
        <label className={`inline-flex cursor-pointer items-center gap-2 font-body text-sm text-ink ${tapArea}`}>
          <input
            type="checkbox"
            checked={onlyNotSent}
            onChange={(e) => setOnlyNotSent(e.target.checked)}
            className="h-4 w-4 rounded border-border accent-primary"
          />
          Show only not sent
        </label>
      </div>

      <section className="overflow-hidden rounded-[24px] border border-border-subtle bg-white">
        {error === "load" ? (
          <p role="alert" className="px-4 py-8 text-center font-body text-sm text-ink-secondary">
            Couldn&apos;t load this list.{" "}
            <button type="button" onClick={() => void loadFirst()} className={`${ghostBtn} ml-1`}>
              Try again
            </button>
          </p>
        ) : rows === null ? (
          <div className="space-y-2 p-4" aria-busy="true" aria-label="Loading messages">
            {[0, 1, 2, 3, 4].map((i) => (
              <div key={i} className="h-11 animate-pulse rounded-xl bg-border-subtle" />
            ))}
          </div>
        ) : rows.length === 0 ? (
          <p className="px-4 py-10 text-center font-body text-sm text-ink-secondary">
            {onlyNotSent
              ? `Every message went out in the last ${days} days.`
              : "Nothing has gone out yet. Messages Anril sends by itself will show here."}
          </p>
        ) : (
          <>
            <table className="hidden w-full font-body text-sm sm:table">
              <thead className="border-b border-border-subtle">
                <tr>
                  <th scope="col" className={TH}>Customer</th>
                  <th scope="col" className={TH}>Message</th>
                  <th scope="col" className={TH}>When</th>
                  <th scope="col" className={TH}>Status</th>
                  <th scope="col" className={TH}>Why</th>
                  <th scope="col" className={TH}>What to do</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-subtle">
                {rows.map((r, i) => (
                  <tr key={`${r.source}-${r.at}-${i}`} className="align-top">
                    <td className="px-4 py-3"><Who row={r} /></td>
                    <td className="px-4 py-3 text-ink">{r.label}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-ink-secondary">{formatWhen(r.at)}</td>
                    <td className="px-4 py-3"><Pill status={r.status} /></td>
                    <td className="max-w-[18rem] break-words px-4 py-3 text-xs text-ink-secondary">{r.why ?? "—"}</td>
                    <td className="px-4 py-3"><Action row={r} /></td>
                  </tr>
                ))}
              </tbody>
            </table>

            <ul className="divide-y divide-border-subtle sm:hidden">
              {rows.map((r, i) => (
                <li key={`${r.source}-${r.at}-${i}`} className="space-y-2 px-4 py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0"><Who row={r} /></div>
                    <Pill status={r.status} />
                  </div>
                  <p className="font-body text-xs text-ink-secondary">{r.label} · {formatWhen(r.at)}</p>
                  {r.why && <p className="break-words font-body text-xs text-ink">{r.why}</p>}
                  <Action row={r} />
                </li>
              ))}
            </ul>
          </>
        )}

        {rows !== null && hasMore && error !== "load" && (
          <div className="flex flex-col items-center gap-2 border-t border-border-subtle px-4 py-3">
            <button type="button" onClick={() => void showMore()} disabled={loadingMore} className={ghostBtn}>
              {loadingMore ? "Loading…" : "Show more"}
            </button>
            {error === "more" && (
              <p role="alert" className="font-body text-xs font-semibold text-danger">
                Couldn&apos;t load more. Try again.
              </p>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
