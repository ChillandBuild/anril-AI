"use client";

import type { SmsMessage } from "@/lib/api";
import { formatIst, formatRupees, statusLabel, statusTone } from "./helpers";
import { Badge } from "./ui";

/** Status badge plus the extra line the contract asks for (reason, charged amount). Never offers a resend. */
export function MessageStatus({ m }: { m: SmsMessage }) {
  const charged = (m.charged_amount ?? 0) > 0;
  return (
    <div className="space-y-1">
      <Badge tone={statusTone(m.status)}>{statusLabel(m.status)}</Badge>
      {(m.status === "failed" || m.status === "skipped") && m.failure_reason && (
        <p className="max-w-[240px] break-words text-xs text-[#64748b]">{m.failure_reason}</p>
      )}
      {m.status === "failed" && charged && <p className="text-xs font-semibold text-[#b45309]">charged {formatRupees(m.charged_amount)}</p>}
    </div>
  );
}

export function messageTime(m: SmsMessage): string {
  return formatIst(m.delivered_at ?? m.submitted_at ?? m.updated_at);
}
