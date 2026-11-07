"use client";

import { CalendarClock, Send } from "lucide-react";
import type { SmsBalance, SmsPreview } from "@/lib/api";
import { formatSendTime } from "@/lib/schedule-time";
import { MANUAL_WARNING, NIGHT_RULE, formatCount, formatRate, formatRupees, languageLine, popupCost, skipCounts } from "./helpers";
import { SenderAvatar } from "./TemplateCard";
import { Btn, Modal, Notice } from "./ui";

/**
 * The check before an SMS goes out: the message as the first person gets it, who gets it and who is
 * skipped, then SMS credits (used, left after) and the ₹ cost at the client's own plan price.
 */
export function SendConfirm({
  open,
  onClose,
  onConfirm,
  submitting,
  preview,
  balance,
  sender,
  source,
  manual,
  sendAt,
  nightRelease,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  submitting: boolean;
  preview: SmsPreview;
  balance: SmsBalance | null;
  sender: string;
  /** "Template #14893" or "DLT Manual · 1707…". */
  source: string;
  manual: boolean;
  /** Set for a scheduled send. */
  sendAt: Date | null;
  /** When the operator's night hold moves it to 10 AM. */
  nightRelease: Date | null;
}) {
  const sample = preview.samples[0] ?? null;
  const cost = popupCost(preview.total_segments, balance);
  const skips = skipCounts(preview);
  const short = cost.left != null && cost.left < 0;
  const people = formatCount(preview.eligible_count);
  const each = sample ? sample.segments : 1;
  const row = "flex items-baseline justify-between gap-3 border-b border-[#eef2f6] py-2 text-sm last:border-b-0";

  return (
    <Modal open={open} title={sendAt ? "Schedule this SMS?" : "Send this SMS now?"} onClose={() => !submitting && onClose()}>
      <div className="space-y-4">
        <div className="rounded-xl bg-[#f8fafc] p-3">
          <p className="mb-2 flex items-center gap-2 text-xs">
            <SenderAvatar sender={sender} />
            <span className="font-bold text-[#0A1528]">{sender}</span>
            <span className="truncate text-[#64748b]">· {source}</span>
          </p>
          {sample && (
            <>
              <p className="whitespace-pre-wrap break-words rounded-2xl rounded-tl-sm bg-white px-3.5 py-2.5 text-sm leading-relaxed text-[#1e293b]">{sample.content}</p>
              <p className="mt-1.5 text-[11px] text-[#64748b]">
                {languageLine(sample.content)}
                {!manual && preview.eligible_count > 0 ? ` · shown with ${sample.name || "the first person"}'s values` : ""}
              </p>
            </>
          )}
        </div>

        <div>
          <p className="text-xs font-bold uppercase tracking-wider text-[#64748b]">Numbers</p>
          <dl>
            <div className={row}>
              <dt className="text-[#64748b]">Will get it</dt>
              <dd className="font-bold text-[#0A1528]">{people} {preview.eligible_count === 1 ? "person" : "people"}</dd>
            </div>
            {skips.rows.map((s) => (
              <div key={s.reason} className={row}>
                <dt className="text-[#64748b]">Skipped: {s.reason}</dt>
                <dd className="font-bold text-[#b45309]">{formatCount(s.count)}</dd>
              </div>
            ))}
            {skips.more > 0 && (
              <div className={row}>
                <dt className="text-[#64748b]">Skipped: other reasons</dt>
                <dd className="font-bold text-[#b45309]">{formatCount(skips.more)}</dd>
              </div>
            )}
          </dl>
        </div>

        <div className="rounded-xl bg-[#f8fafc] px-4 py-3">
          <div className="flex items-baseline justify-between gap-3">
            <span className="text-sm text-[#64748b]">SMS credits used</span>
            <span className="font-display text-2xl font-bold text-[#0A1528]">{formatCount(cost.credits)}</span>
          </div>
          <p className="mb-1 text-right text-[11px] text-[#94a3b8]">
            {preview.eligible_count * each === preview.total_segments
              ? `${people} × ${formatCount(each)} SMS each`
              : `For ${people} people. Some messages are longer, so they count as more than 1 SMS.`}
          </p>
          <dl>
            <div className={row}>
              <dt className="text-[#64748b]">Credits left after</dt>
              <dd className={short ? "font-bold text-danger" : "font-bold text-[#0A1528]"}>
                {cost.left == null ? "—" : short ? "Not enough" : formatCount(cost.left)}
              </dd>
            </div>
            {cost.rupees != null && cost.rate != null && (
              <div className={row}>
                <dt className="text-[#64748b]">Cost from your plan</dt>
                <dd className="text-right font-bold text-[#0A1528]">
                  {formatRupees(cost.rupees)} <span className="font-normal text-[#64748b]">({formatRate(cost.rate)} per SMS)</span>
                </dd>
              </div>
            )}
          </dl>
        </div>

        {short && balance && (
          <Notice tone="danger">
            You have {formatCount(balance.sms_count)} SMS credits and this needs {formatCount(cost.credits)}. Top up {formatCount(-(cost.left ?? 0))} more to send it.
          </Notice>
        )}
        {manual && <Notice tone="warn">{MANUAL_WARNING}</Notice>}
        {nightRelease && (
          <Notice tone="warn">
            It goes out at {formatSendTime(nightRelease)}, not straight away. {NIGHT_RULE}
          </Notice>
        )}
        <p className="flex items-center gap-2 text-xs text-[#64748b]">
          {sendAt ? <CalendarClock size={14} /> : <Send size={14} />}
          {sendAt ? `Goes out ${formatSendTime(sendAt)} IST.` : "Goes out right away. Sending can't be undone once it starts."}
        </p>

        <div className="flex justify-end gap-2">
          <Btn variant="outline" disabled={submitting} onClick={onClose}>
            Cancel
          </Btn>
          <Btn busy={submitting} disabled={short || preview.eligible_count === 0} onClick={onConfirm}>
            {short ? "Not enough credits" : `${sendAt ? "Schedule for" : "Send to"} ${people} ${preview.eligible_count === 1 ? "person" : "people"}`}
          </Btn>
        </div>
      </div>
    </Modal>
  );
}
