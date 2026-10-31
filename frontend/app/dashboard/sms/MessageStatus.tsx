"use client";

import type { SmsMessage } from "@/lib/api";
import { formatIst, statusLabel, statusTone } from "./helpers";
import { Badge } from "./ui";

export function MessageStatus({ m }: { m: SmsMessage }) {
  return (
    <div className="space-y-1">
      <Badge tone={statusTone(m.status)}>{statusLabel(m.status)}</Badge>
      {(m.status === "failed" || m.status === "skipped") && m.failure_reason && (
        <p className="max-w-[240px] break-words text-xs text-[#64748b]">{m.failure_reason}</p>
      )}
    </div>
  );
}

export function messageTime(m: SmsMessage): string {
  return formatIst(m.delivered_at ?? m.submitted_at ?? m.updated_at);
}
