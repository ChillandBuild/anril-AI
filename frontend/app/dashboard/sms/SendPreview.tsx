"use client";

import type { SmsPreview } from "@/lib/api";
import { formatCount, groupExcluded } from "./helpers";
import { Notice } from "./ui";

/** Under the Send SMS preview: who was skipped and why, and a Unicode note. Credits and ₹ are in the Send popup. */
export function SendPreview({ preview }: { preview: SmsPreview }) {
  const skipped = preview.excluded_total ?? preview.excluded.length;
  const groups = groupExcluded(preview.excluded);
  const anyUnicode = preview.samples.some((s) => s.unicode);
  return (
    <div className="space-y-2">
      {skipped > 0 && <p className="text-xs font-semibold text-[#b45309]">{formatCount(skipped)} skipped. Open a reason to see who.</p>}
      {anyUnicode && (
        <p className="text-xs text-[#b45309]">
          Some text isn&apos;t plain English letters (Unicode). These messages are shorter per SMS, so they can use more than one SMS each and use more credits.
        </p>
      )}
      {groups.length > 0 && (
        <div className="space-y-2">
          {groups.map((g) => (
            <details key={g.reason} className="rounded-xl border border-[#e2e8f0] bg-white px-3 py-2">
              <summary className="cursor-pointer text-sm font-semibold text-[#0A1528]">
                {g.reason} <span className="font-normal text-[#64748b]">· {formatCount(g.leads.length)}</span>
              </summary>
              <ul className="mt-2 max-h-40 space-y-1 overflow-y-auto text-xs text-[#64748b]">
                {g.leads.slice(0, 200).map((l, i) => (
                  <li key={l.lead_id ?? i} className="truncate">
                    {l.name || "No name"} · {l.phone ?? "no number"}
                  </li>
                ))}
                {g.leads.length > 200 && <li>and {formatCount(g.leads.length - 200)} more</li>}
              </ul>
            </details>
          ))}
        </div>
      )}
      {preview.eligible_count === 0 && <Notice tone="warn">No one is left to send to. Change the numbers to try again.</Notice>}
    </div>
  );
}
