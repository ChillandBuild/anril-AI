"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type AutoMessageEvents, type AutoMessageSend, type PrivateSendStatus } from "@/lib/api";
import { Select } from "@/components/ui/Select";
import { PrivateSendDailyTable } from "./PrivateSend";
import { EVENT_LABEL, SENT_BY_APP, SOURCE_LABEL, STATUS_STYLE, formatWhen, ghostBtn, reasonText } from "./shared";

const FIRST_PAGE = 10;
const NEXT_PAGE = 25;

const STATUS_FILTERS: { id: string; label: string }[] = [
  { id: "", label: "All statuses" },
  { id: "sent", label: "Sent" },
  { id: "queued", label: "Scheduled" },
  { id: "skipped", label: "Not sent" },
  { id: "failed", label: "Failed" },
];

const TH = "px-3 py-2 text-left sm:px-4 font-label text-[10px] font-bold uppercase tracking-wide text-ink-secondary";

function StatusCell({ send }: { send: AutoMessageSend }) {
  const style = STATUS_STYLE[send.status];
  const why = reasonText(send.status, send.reason);
  return (
    <div className="flex flex-col items-start gap-1 sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-2">
      <span className={`whitespace-nowrap rounded-full border px-2.5 py-0.5 font-label text-[10px] font-bold ${style.cls}`}>{style.label}</span>
      {why && <span className="min-w-0 break-words font-body text-xs text-ink-secondary max-sm:w-full">{why}</span>}
      {send.status === "queued" && !why && (
        <span className="font-body text-xs text-ink-secondary">goes at {formatWhen(send.send_at)}</span>
      )}
    </div>
  );
}

export function ActivitySection({ privateSend }: { privateSend: PrivateSendStatus | null }) {
  const [events, setEvents] = useState<AutoMessageEvents | null>(null);
  const [event, setEvent] = useState("");
  const [status, setStatus] = useState("");
  const [rows, setRows] = useState<AutoMessageSend[] | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState<"load" | "more" | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  // Only the newest request may write to the list (filters can change while one is in flight).
  const requestId = useRef(0);

  useEffect(() => {
    api.autoMessages.events().then(setEvents).catch(() => undefined);
  }, []);

  const loadFirst = useCallback(async () => {
    const id = ++requestId.current;
    setRows(null);
    setError(null);
    try {
      const page = await api.autoMessages.sends({ event, status, limit: FIRST_PAGE, offset: 0 });
      if (id !== requestId.current) return;
      setRows(page.sends);
      setHasMore(page.has_more);
    } catch {
      if (id === requestId.current) setError("load");
    }
  }, [event, status]);

  useEffect(() => {
    if (!privateSend) void loadFirst();
  }, [loadFirst, privateSend]);

  async function showMore() {
    if (!rows) return;
    const id = requestId.current;
    setLoadingMore(true);
    setError(null);
    try {
      const page = await api.autoMessages.sends({ event, status, limit: NEXT_PAGE, offset: rows.length });
      if (id !== requestId.current) return;
      setRows((prev) => [...(prev ?? []), ...page.sends]);
      setHasMore(page.has_more);
    } catch {
      if (id === requestId.current) setError("more");
    } finally {
      setLoadingMore(false);
    }
  }

  if (privateSend) return <PrivateSendDailyTable status={privateSend} />;

  const eventOptions = [...(events?.builtin ?? []), ...(events?.custom ?? [])];
  const labelFor = (key: string) =>
    eventOptions.find((e) => e.key === key)?.label ?? EVENT_LABEL[key] ?? key.replace(/_/g, " ");
  /** An app that sent a template ID directly has no event, so say who sent it instead. */
  const eventText = (s: AutoMessageSend) => (s.event ? labelFor(s.event) : SENT_BY_APP);
  const filtered = event !== "" || status !== "";

  return (
    <section className="overflow-hidden rounded-[24px] border border-border-subtle bg-white">
      <div className="flex flex-wrap gap-2 border-b border-border-subtle px-3 py-3 sm:px-4">
        <Select
          size="sm"
          aria-label="Filter by event"
          className="w-auto min-w-[140px]"
          value={event}
          onChange={setEvent}
          options={[{ value: "", label: "All events" }, ...eventOptions.map((o) => ({ value: o.key, label: o.label }))]}
        />
        <Select
          size="sm"
          aria-label="Filter by status"
          className="w-auto min-w-[140px]"
          value={status}
          onChange={setStatus}
          options={STATUS_FILTERS.map((f) => ({ value: f.id, label: f.label }))}
        />
      </div>

      {error === "load" ? (
        <p role="alert" className="px-4 py-8 text-center font-body text-sm text-ink-secondary">
          Couldn&apos;t load activity.{" "}
          <button type="button" onClick={() => void loadFirst()} className={`${ghostBtn} ml-1`}>
            Try again
          </button>
        </p>
      ) : rows === null ? (
        <div className="space-y-2 p-4" aria-busy="true" aria-label="Loading activity">
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="h-11 animate-pulse rounded-xl bg-border-subtle" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <p className="px-4 py-10 text-center font-body text-sm text-ink-secondary">
          {filtered ? "Nothing matches these filters." : "No messages yet. They'll appear here as customers come in."}
        </p>
      ) : (
        <table className="w-full table-fixed font-body text-sm sm:table-auto">
          <thead className="border-b border-border-subtle">
            <tr>
              <th scope="col" className={`${TH} max-sm:w-[40%]`}>Customer</th>
              <th scope="col" className={`${TH} hidden sm:table-cell`}>Event</th>
              <th scope="col" className={`${TH} hidden sm:table-cell`}>Template</th>
              <th scope="col" className={`${TH} max-sm:w-[60%]`}>Status</th>
              <th scope="col" className={`${TH} hidden sm:table-cell`}>When</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border-subtle">
            {rows.map((s) => (
              <tr key={s.id} className="align-top">
                <td className="px-3 py-3 sm:px-4">
                  {s.name ? (
                    <>
                      <p className="break-words font-semibold text-ink">{s.name}</p>
                      <p className="truncate whitespace-nowrap text-xs text-ink-secondary" title={s.phone}>{s.phone}</p>
                    </>
                  ) : (
                    <p className="truncate whitespace-nowrap font-semibold text-ink" title={s.phone}>{s.phone}</p>
                  )}
                  <div className="mt-0.5 space-y-0.5 text-[11px] text-ink-secondary sm:hidden">
                    <p className="truncate">{eventText(s)} · {formatWhen(s.created_at)}</p>
                    {s.template_name && (
                      <p className="truncate whitespace-nowrap font-mono" title={s.template_name}>{s.template_name}</p>
                    )}
                  </div>
                </td>
                <td className="hidden px-4 py-3 text-ink sm:table-cell">
                  {eventText(s)}
                  {s.source === "partner" && (
                    <span className="block text-[11px] text-ink-secondary">{SOURCE_LABEL.partner}</span>
                  )}
                </td>
                <td className="hidden px-4 py-3 font-mono text-[12px] text-ink-secondary sm:table-cell">{s.template_name ?? "—"}</td>
                <td className="px-3 py-3 sm:px-4">
                  <StatusCell send={s} />
                </td>
                <td className="hidden whitespace-nowrap px-4 py-3 text-ink-secondary sm:table-cell">{formatWhen(s.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
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
  );
}
