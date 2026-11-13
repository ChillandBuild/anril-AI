"use client";

import { useState } from "react";
import useSWR from "swr";
import { ArrowLeft } from "lucide-react";
import { toast } from "sonner";
import { Select } from "@/components/ui/Select";
import { ConfirmModal } from "@/components/ConfirmModal";
import { api, type SmsMessageStatus } from "@/lib/api";
import { MobileRecordCard, MobileRecordField, MobileRecordGrid } from "@/components/MobileRecord";
import {
  MESSAGE_STATUSES,
  campaignStage,
  campaignNeedsUpdates,
  canCancelCampaign,
  canDeleteCampaign,
  canRescheduleCampaign,
  errorText,
  formatCount,
  formatIst,
  formatRupees,
  friendlyError,
  fromLocalInput,
  statusLabel,
  toLocalInput,
  NIGHT_RULE,
  categoryLabel,
  quietRelease,
} from "./helpers";
import { formatSendTime } from "@/lib/schedule-time";
import { MessageStatus, messageTime } from "./MessageStatus";
import { Badge, Btn, Card, CardHeader, Empty, Field, LoadError, Notice, Skeleton, TableWrap, tdCls, thCls, inputCls } from "./ui";
import { usePerm } from "./usePerm";

const PAGE = 50;

export function CampaignDetail({ id, onBack, onChanged }: { id: string; onBack: () => void; onChanged: () => void }) {
  const { canManage } = usePerm();
  const [status, setStatus] = useState<"" | SmsMessageStatus>("");
  const [offset, setOffset] = useState(0);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [moving, setMoving] = useState(false);
  const [moveAt, setMoveAt] = useState("");
  const [moveBusy, setMoveBusy] = useState(false);
  const [moveError, setMoveError] = useState<string | null>(null);

  const campaign = useSWR(["sms:campaign", id], () => api.sms.campaign(id), {
    refreshInterval: (c) => (campaignNeedsUpdates(c) ? 10_000 : 0),
  });
  const live = campaignNeedsUpdates(campaign.data);
  const messages = useSWR(
    ["sms:campaign-messages", id, status, offset],
    () => api.sms.messages({ campaign_id: id, status: status || undefined, limit: PAGE, offset }),
    { keepPreviousData: true, refreshInterval: live ? 10_000 : 0 },
  );

  async function cancel() {
    setCancelling(true);
    try {
      await api.sms.cancelCampaign(id);
      toast.success("Send cancelled. Waiting messages will not be sent.");
      setConfirmCancel(false);
      await campaign.mutate();
      await messages.mutate();
      onChanged();
    } catch (err) {
      toast.error(friendlyError(err, "Couldn't cancel this send"));
      setConfirmCancel(false);
      void campaign.mutate();
    } finally {
      setCancelling(false);
    }
  }

  async function reschedule() {
    const sendAt = fromLocalInput(moveAt);
    if (!sendAt) {
      setMoveError("Pick a future date and time.");
      return;
    }
    setMoveBusy(true);
    setMoveError(null);
    try {
      await api.sms.rescheduleCampaign(id, sendAt);
      toast.success("Send rescheduled.");
      setMoving(false);
      await campaign.mutate();
      onChanged();
    } catch (err) {
      setMoveError(errorText(err, "Couldn't reschedule this send"));
      void campaign.mutate();
    } finally {
      setMoveBusy(false);
    }
  }

  async function remove() {
    setDeleting(true);
    try {
      await api.sms.deleteCampaign(id);
      toast.success("Send deleted.");
      setConfirmDelete(false);
      onChanged();
      onBack();
    } catch (err) {
      toast.error(errorText(err, "Couldn't delete this send"));
      setConfirmDelete(false);
      void campaign.mutate();
    } finally {
      setDeleting(false);
    }
  }

  const c = campaign.data;
  // Sent to the operator between 9 PM and 10 AM: still held until 10 AM.
  const nightRelease = c && c.counts.submitted > 0 ? quietRelease(c.send_at ?? c.created_at) : null;
  const heldRelease = nightRelease && new Date() < nightRelease ? nightRelease : null;
  const rows = messages.data?.messages ?? [];
  const total = messages.data?.total ?? 0;

  return (
    <div className="w-full space-y-4">
      <button type="button" onClick={onBack} className="flex items-center gap-1 text-sm font-bold text-primary hover:underline">
        <ArrowLeft size={15} /> All reports
      </button>

      {campaign.isLoading && !c ? (
        <Skeleton className="h-40" />
      ) : campaign.error && !c ? (
        <Card>
          <LoadError message={friendlyError(campaign.error, "Check your connection.")} onRetry={() => void campaign.mutate()} />
        </Card>
      ) : c ? (
        <Card>
          <div className="space-y-4 p-4 sm:p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <h1 className="break-words font-display text-xl font-bold text-[#0A1528]">{c.name}</h1>
                <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-[#64748b]">
                  <Badge tone={campaignStage(c, new Date()).tone}>{campaignStage(c, new Date()).label}</Badge>
                  <span>Sender {c.sender_id}</span>
                  <span>{c.kind === "manual" ? "Typed with DLT IDs" : categoryLabel(c.template_type)}</span>
                  {c.status === "scheduled" && c.send_at ? <span>Goes out {formatIst(c.send_at)} IST</span> : <span>Created {formatIst(c.created_at)}</span>}
                </div>
              </div>
              {canCancelCampaign(c.status) && canManage && (
                <div className="flex flex-wrap gap-2">
                  {canRescheduleCampaign(c.status) && (
                    <Btn
                      variant="outline"
                      onClick={() => {
                        setMoveAt(toLocalInput(c.send_at));
                        setMoveError(null);
                        setMoving((open) => !open);
                      }}
                    >
                      Reschedule
                    </Btn>
                  )}
                  <Btn variant="danger" onClick={() => setConfirmCancel(true)}>
                    Cancel this send
                  </Btn>
                </div>
              )}
              {canDeleteCampaign(c.status) && canManage && (
                <Btn variant="danger" onClick={() => setConfirmDelete(true)}>
                  Delete
                </Btn>
              )}
            </div>
            {moving && canRescheduleCampaign(c.status) && canManage && (
              <div className="space-y-3 rounded-xl border border-[#e2e8f0] p-3">
                <Field label="New send time (your local time)">
                  <input type="datetime-local" className={`${inputCls} sm:w-64`} value={moveAt} onChange={(e) => setMoveAt(e.target.value)} />
                </Field>
                {moveError && <Notice tone="warn">{moveError}</Notice>}
                <div className="flex gap-2">
                  <Btn busy={moveBusy} disabled={!moveAt} onClick={() => void reschedule()}>
                    Save
                  </Btn>
                  <Btn variant="outline" disabled={moveBusy} onClick={() => setMoving(false)}>
                    Cancel
                  </Btn>
                </div>
              </div>
            )}
            {c.build_error && <Notice tone="danger">{c.build_error}</Notice>}
            {c.status === "preparing" && !c.build_error && <Notice tone="info">We&apos;re building your recipient list. Sending starts when it&apos;s ready.</Notice>}
            {heldRelease && (
              <Notice tone="warn">
                {formatCount(c.counts.submitted)} SMS will go out at {formatSendTime(heldRelease)}. {NIGHT_RULE}
              </Notice>
            )}
            <p className="whitespace-pre-wrap break-words rounded-xl bg-[#f8fafc] p-3 text-sm text-[#334155]">{c.template_text}</p>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-5">
              <Stat label="Total" value={formatCount(c.total)} />
              <Stat label="Delivered" value={formatCount(c.counts.delivered)} tone="text-[#15803d]" />
              <Stat label="Sent to operator" value={formatCount(c.counts.submitted)} />
              <Stat label="Failed" value={formatCount(c.counts.failed)} tone="text-[#be123c]" />
              <Stat label="Waiting" value={formatCount(c.counts.queued + c.counts.sending)} />
              <Stat label="Checking…" value={formatCount(c.counts.unknown)} />
              <Stat label="Not sent" value={formatCount(c.counts.skipped)} />
              <Stat label="Cancelled" value={formatCount(c.counts.cancelled)} />
              <Stat label="SMS used" value={formatCount(c.sms_used)} />
              {c.amount_debited != null && <Stat label="Cost" value={formatRupees(c.amount_debited)} />}
            </div>
            {c.counts.unknown > 0 && (
              <Notice tone="info">
                Some messages are still being checked with the operator. We&apos;ll update them automatically; there is nothing to resend.
              </Notice>
            )}
          </div>
        </Card>
      ) : null}

      <Card>
        <CardHeader
          title="Messages"
          action={
            <Select
              aria-label="Filter by status"
              size="sm"
              className="w-auto min-w-[160px]"
              value={status}
              onChange={(v) => {
                setStatus(v as "" | SmsMessageStatus);
                setOffset(0);
              }}
              options={[{ value: "", label: "All statuses" }, ...MESSAGE_STATUSES.map((s) => ({ value: s, label: statusLabel(s) }))]}
            />
          }
        />
        {messages.isLoading && !messages.data ? (
          <div className="m-4 h-48 animate-pulse rounded-xl bg-border-subtle" />
        ) : messages.error && !messages.data ? (
          <LoadError message={friendlyError(messages.error, "Check your connection.")} onRetry={() => void messages.mutate()} />
        ) : rows.length === 0 ? (
          <Empty title="No messages here." />
        ) : (
          <>
            <div className="hidden md:block">
              <TableWrap>
                <table className="w-full min-w-[720px]">
                  <thead>
                    <tr className="border-b border-[#f1f5f9]">
                      <th className={thCls}>Lead</th>
                      <th className={thCls}>Number</th>
                      <th className={thCls}>Status</th>
                      <th className={thCls}>SMS</th>
                      <th className={thCls}>Time (IST)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((m) => (
                      <tr key={m.id} className="border-b border-[#f1f5f9] last:border-0">
                        <td className={tdCls}>{m.lead_name || "—"}</td>
                        <td className={`${tdCls} whitespace-nowrap`}>{m.phone}</td>
                        <td className={tdCls}>
                          <MessageStatus m={m} />
                        </td>
                        <td className={tdCls}>{m.sms_count ?? "—"}</td>
                        <td className={`${tdCls} whitespace-nowrap`}>{messageTime(m)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableWrap>
            </div>
            <div className="space-y-3 p-3 md:hidden">
              {rows.map((m) => (
                <MobileRecordCard key={m.id}>
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-bold text-[#0A1528]">{m.lead_name || m.phone}</p>
                      <p className="text-xs text-[#64748b]">{m.phone}</p>
                    </div>
                    <MessageStatus m={m} />
                  </div>
                  <MobileRecordGrid>
                    <MobileRecordField label="SMS" value={m.sms_count ?? "—"} />
                    <MobileRecordField className="col-span-2" label="Time (IST)" value={messageTime(m)} />
                  </MobileRecordGrid>
                </MobileRecordCard>
              ))}
            </div>
            <Pager offset={offset} limit={PAGE} total={total} onOffset={setOffset} />
          </>
        )}
      </Card>

      <ConfirmModal
        open={confirmCancel}
        onClose={() => !cancelling && setConfirmCancel(false)}
        onConfirm={() => void cancel()}
        title="Cancel this send?"
        description="Nothing has been sent yet. Cancelling stops every waiting message."
        tone="danger"
        confirmLabel="Cancel this send"
        cancelLabel="Keep it"
        loading={cancelling}
        loadingLabel="Cancelling…"
      />

      <ConfirmModal
        open={confirmDelete}
        onClose={() => !deleting && setConfirmDelete(false)}
        onConfirm={() => void remove()}
        title="Delete this send?"
        description="It disappears from Your sends. The messages it sent and what they cost stay in Reports and Balance history."
        tone="danger"
        confirmLabel="Delete"
        cancelLabel="Keep it"
        loading={deleting}
        loadingLabel="Deleting…"
      />
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-xl bg-[#f8fafc] px-3 py-2.5">
      <p className="text-[10px] font-bold uppercase tracking-wider text-[#64748b]">{label}</p>
      <p className={`mt-0.5 font-display text-lg font-bold ${tone ?? "text-[#0A1528]"}`}>{value}</p>
    </div>
  );
}

export function Pager({ offset, limit, total, onOffset }: { offset: number; limit: number; total: number; onOffset: (o: number) => void }) {
  if (total <= limit) return null;
  const from = offset + 1;
  const to = Math.min(offset + limit, total);
  return (
    <div className="flex items-center justify-between gap-2 border-t border-[#f1f5f9] px-4 py-3 text-xs text-[#64748b]">
      <span>
        {formatCount(from)}–{formatCount(to)} of {formatCount(total)}
      </span>
      <div className="flex gap-2">
        <Btn variant="outline" className="h-8 text-xs" disabled={offset <= 0} onClick={() => onOffset(Math.max(0, offset - limit))}>
          Previous
        </Btn>
        <Btn variant="outline" className="h-8 text-xs" disabled={offset + limit >= total} onClick={() => onOffset(offset + limit)}>
          Next
        </Btn>
      </div>
    </div>
  );
}
