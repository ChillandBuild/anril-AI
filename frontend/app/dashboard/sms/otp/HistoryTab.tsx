"use client";

import { useState, type KeyboardEvent, type ReactNode } from "react";
import useSWR from "swr";
import { api, type OtpHistoryItem } from "@/lib/api";
import { formatIst } from "../helpers";
import { Badge, Btn, Card, CardHeader, Empty, LoadError, Modal, Notice, Skeleton, TableWrap, tdCls, thCls } from "../ui";
import {
  ChannelBadge,
  ORIGIN_LABELS,
  ResultBadge,
  modeShortLabel,
  otpError,
  sourceLabel,
} from "./otpShared";

const PAGE = 25;
const HISTORY_KEY = "otp:history";

export function HistoryTab() {
  const { data, error, isLoading, isValidating, mutate } = useSWR(HISTORY_KEY, () => api.otp.history({ limit: PAGE }), {
    revalidateOnFocus: false,
  });
  // Pages after the first, loaded with "Load more". The first page lives in SWR.
  const [older, setOlder] = useState<OtpHistoryItem[]>([]);
  const [exhausted, setExhausted] = useState(false);
  const [moreBusy, setMoreBusy] = useState(false);
  const [moreError, setMoreError] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);

  const items = [...(data?.items ?? []), ...older];
  const canLoadMore = !exhausted && (data?.items.length ?? 0) === PAGE;

  async function loadMore() {
    const last = items[items.length - 1];
    if (!last) return;
    setMoreBusy(true);
    setMoreError("");
    try {
      const res = await api.otp.history({ before: last.created_at, limit: PAGE });
      setOlder((prev) => [...prev, ...res.items]);
      if (res.items.length < PAGE) setExhausted(true);
    } catch (err) {
      setMoreError(otpError(err, "Couldn't load more. Try again."));
    } finally {
      setMoreBusy(false);
    }
  }

  function refresh() {
    setOlder([]);
    setExhausted(false);
    setMoreError("");
    void mutate();
  }

  return (
    <Card>
      <CardHeader
        title="History"
        hint="Every code sent, newest first. Tap a row for the details."
        action={
          <Btn variant="outline" className="h-9" busy={isValidating && !isLoading} onClick={refresh}>
            Refresh
          </Btn>
        }
      />

      {error && !data ? (
        <LoadError message={otpError(error, "Try again in a moment.")} onRetry={refresh} />
      ) : isLoading || !data ? (
        <div className="space-y-2 p-4">
          <Skeleton className="h-12" />
          <Skeleton className="h-12" />
          <Skeleton className="h-12" />
        </div>
      ) : items.length === 0 ? (
        <Empty title="No codes yet" hint="Codes you send from Send & check, the API or the WhatsApp bot show up here." />
      ) : (
        <>
          <TableWrap>
            <table className="w-full min-w-[860px]">
              <thead className="bg-[#f8fafc]">
                <tr>
                  <th className={thCls}>Time</th>
                  <th className={thCls}>Number</th>
                  <th className={thCls}>How sent</th>
                  <th className={thCls}>Code</th>
                  <th className={thCls}>SMS</th>
                  <th className={thCls}>WhatsApp</th>
                  <th className={thCls}>Result</th>
                  <th className={thCls}>From</th>
                </tr>
              </thead>
              <tbody>
                {items.map((it) => (
                  <HistoryRow key={it.otp_id} item={it} onOpen={() => setOpenId(it.otp_id)} />
                ))}
              </tbody>
            </table>
          </TableWrap>

          <div className="space-y-2 border-t border-[#e2e8f0] px-4 py-3 text-center">
            {moreError && <Notice tone="danger">{moreError}</Notice>}
            {canLoadMore && (
              <Btn variant="outline" className="h-9" busy={moreBusy} onClick={() => void loadMore()}>
                Load more
              </Btn>
            )}
          </div>
        </>
      )}

      <Modal open={openId !== null} title="OTP details" onClose={() => setOpenId(null)} wide>
        {openId && <OtpDetail id={openId} />}
      </Modal>
    </Card>
  );
}

function HistoryRow({ item, onOpen }: { item: OtpHistoryItem; onOpen: () => void }) {
  function onKey(e: KeyboardEvent<HTMLTableRowElement>) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onOpen();
    }
  }
  return (
    <tr
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={onKey}
      className="cursor-pointer border-t border-[#e2e8f0] transition-colors hover:bg-[#f8fafc] focus-visible:bg-[#f8fafc] focus-visible:outline-none"
    >
      <td className={`${tdCls} whitespace-nowrap`}>{formatIst(item.created_at)}</td>
      <td className={`${tdCls} whitespace-nowrap font-semibold text-[#0A1528]`}>{item.phone}</td>
      <td className={`${tdCls} whitespace-nowrap`}>
        {modeShortLabel(item.mode)}
        <span className="block text-xs text-[#64748b]">Made by {item.source === "anril" ? "Anril" : "your server"}</span>
      </td>
      <td className={`${tdCls} whitespace-nowrap font-mono`}>{item.code || "—"}</td>
      <td className={tdCls}>
        <ChannelBadge status={item.sms.status} />
      </td>
      <td className={tdCls}>
        <ChannelBadge status={item.whatsapp.status} />
      </td>
      <td className={tdCls}>
        <div className="flex flex-wrap gap-1.5">
          <ResultBadge status={item.status} />
          {item.not_requested && item.status !== "not_requested" && <Badge tone="danger">Didn&apos;t ask for it</Badge>}
        </div>
      </td>
      <td className={`${tdCls} whitespace-nowrap`}>{ORIGIN_LABELS[item.origin]}</td>
    </tr>
  );
}

function OtpDetail({ id }: { id: string }) {
  const { data, error, isLoading, mutate } = useSWR(["otp:detail", id], () => api.otp.historyItem(id), {
    revalidateOnFocus: false,
  });

  if (error && !data) {
    return <LoadError message={otpError(error, "Try again in a moment.")} onRetry={() => void mutate()} />;
  }
  if (isLoading || !data) return <Skeleton className="h-64" />;

  const it = data.item;
  return (
    <div className="space-y-5">
      <dl className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
        <DetailRow label="Number">{it.phone}</DetailRow>
        <DetailRow label="Time">{formatIst(it.created_at)}</DetailRow>
        <DetailRow label="How sent">{modeShortLabel(it.mode)}</DetailRow>
        <DetailRow label="Made by">{sourceLabel(it.source)}</DetailRow>
        <DetailRow label="From">{ORIGIN_LABELS[it.origin]}</DetailRow>
        <DetailRow label="Code">
          <span className="font-mono">{it.code || "—"}</span>
        </DetailRow>
        <DetailRow label="Tries used">{String(it.attempts)}</DetailRow>
        <DetailRow label="Expires">{formatIst(it.expires_at)}</DetailRow>
        <DetailRow label="Result">
          <div className="flex flex-wrap gap-1.5">
            <ResultBadge status={it.status} />
            {it.not_requested && it.status !== "not_requested" && <Badge tone="danger">Didn&apos;t ask for it</Badge>}
          </div>
        </DetailRow>
        <DetailRow label="Verified at">{it.verified_at ? formatIst(it.verified_at) : "Not verified"}</DetailRow>
        <DetailRow label="SMS">
          <div className="space-y-1">
            <ChannelBadge status={it.sms.status} />
            {it.sms.error && <p className="break-words text-xs text-danger">{it.sms.error}</p>}
          </div>
        </DetailRow>
        <DetailRow label="WhatsApp">
          <div className="space-y-1">
            <div className="flex flex-wrap gap-1.5">
              <ChannelBadge status={it.whatsapp.status} />
              {it.whatsapp_backup_sent && <Badge tone="info">WhatsApp backup sent</Badge>}
            </div>
            {it.whatsapp.error && <p className="break-words text-xs text-danger">{it.whatsapp.error}</p>}
          </div>
        </DetailRow>
      </dl>

      <div className="space-y-2">
        <h3 className="font-display text-sm font-bold text-[#0A1528]">Updates</h3>
        {data.updates.length === 0 ? (
          <p className="text-sm text-[#64748b]">No updates yet.</p>
        ) : (
          <ul className="space-y-2">
            {data.updates.map((u, i) => {
              const tone = u.status === "delivered" ? "success" : u.status === "failed" ? "danger" : "neutral";
              const label = u.status === "delivered" ? "Delivered" : u.status === "failed" ? "Failed" : capitalize(u.status);
              return (
                <li key={`${u.event}-${u.created_at}-${i}`} className="flex flex-wrap items-start justify-between gap-2 rounded-xl border border-[#e2e8f0] px-3 py-2.5">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold text-[#0A1528]">{capitalize(u.event.replace(/_/g, " "))}</p>
                    <p className="text-xs text-[#64748b]">
                      {`${formatIst(u.created_at)} · Attempts: ${u.attempts}`}
                      {u.delivered_at ? ` · Delivered ${formatIst(u.delivered_at)}` : ""}
                    </p>
                    {u.last_error && <p className="mt-1 break-words text-xs text-danger">{u.last_error}</p>}
                  </div>
                  <Badge tone={tone}>{label}</Badge>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}

function DetailRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs font-bold text-[#64748b]">{label}</dt>
      <dd className="mt-1 break-words text-sm text-[#0A1528]">{children}</dd>
    </div>
  );
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
