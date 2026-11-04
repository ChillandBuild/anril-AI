"use client";

import type { SmsMessage } from "@/lib/api";
import { clockOf } from "@/lib/schedule-time";
import { NIGHT_RULE, dltReason, formatIst, heldUntil, statusLabel, statusTone } from "./helpers";
import { Badge } from "./ui";

export function MessageStatus({ m }: { m: SmsMessage }) {
  const reason = dltReason(m.failure_reason);
  const held = heldUntil(m, new Date());
  if (held) {
    return (
      <div className="space-y-1">
        <Badge tone="warn">Held until {clockOf(held)}</Badge>
        <p className="max-w-[240px] break-words text-xs text-[#64748b]">{NIGHT_RULE}</p>
      </div>
    );
  }
  return (
    <div className="space-y-1">
      <Badge tone={statusTone(m.status)}>{statusLabel(m.status)}</Badge>
      {(m.status === "failed" || m.status === "skipped") && reason.text && (
        <p className="max-w-[240px] break-words text-xs text-[#64748b]" title={reason.code ?? undefined}>
          {reason.text}
          {reason.code && reason.code.toLowerCase() !== reason.text.toLowerCase() && <span className="mt-0.5 block text-[10px] text-[#94a3b8]">{reason.code}</span>}
        </p>
      )}
    </div>
  );
}

export function messageTime(m: SmsMessage): string {
  return formatIst(m.delivered_at ?? m.submitted_at ?? m.updated_at);
}
