"use client";

import type { SmsPreview } from "@/lib/api";
import { estimateLine, formatCount, groupExcluded } from "./helpers";
import { Notice } from "./ui";

/** "4,210 will get it · 62 skipped (why) · ≈ ₹760", plus samples and the skipped reasons. */
export function SendPreview({ preview }: { preview: SmsPreview }) {
  const skipped = preview.excluded_total ?? preview.excluded.length;
  const groups = groupExcluded(preview.excluded);
  const why = groups.slice(0, 3).map((g) => g.reason).join("; ");
  const cost = estimateLine(preview);
  const anyUnicode = preview.samples.some((s) => s.unicode);
  return (
    <div className="space-y-3 rounded-xl bg-[#f8fafc] p-3.5">
      <p className="text-sm font-bold text-[#0A1528]">
        {formatCount(preview.eligible_count)} will get it
        {skipped > 0 && <span className="font-normal text-[#b45309]"> · {formatCount(skipped)} skipped{why ? ` (${why})` : ""}</span>}
        <span className="font-normal text-[#64748b]"> · {formatCount(preview.total_segments)} SMS credits</span>
        {cost.known && preview.estimated_amount != null && <span className="font-normal text-[#334155]"> · {cost.text}</span>}
      </p>
      {!cost.known && <p className="text-xs text-[#64748b]">{cost.text}</p>}
      {preview.samples.length > 0 && (
        <ul className="space-y-2">
          {preview.samples.map((s, i) => (
            <li key={s.lead_id ?? i} className="rounded-xl border border-[#e2e8f0] bg-white p-3">
              <p className="whitespace-pre-wrap break-words text-sm text-[#0A1528]">{s.content}</p>
              <p className="mt-1.5 text-xs text-[#64748b]">
                To {s.name || "recipient"} · {s.segments} SMS{s.segments === 1 ? "" : "s"} each{s.unicode ? " · uses non-English characters" : ""}
              </p>
            </li>
          ))}
        </ul>
      )}
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
      {preview.eligible_count === 0 && <Notice tone="warn">No one is left to send to. Change the numbers and preview again.</Notice>}
    </div>
  );
}
