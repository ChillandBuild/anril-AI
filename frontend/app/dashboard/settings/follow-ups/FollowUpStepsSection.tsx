"use client";

import { useEffect, useState } from "react";
import { api, BroadcastHistoryItem, WabaTemplate } from "@/lib/api";
import { Select } from "@/components/ui/Select";
import ReengagementBuilder from "@/app/dashboard/leads/ReengagementBuilder";

// Radix Select cannot hold an empty item value, so "any campaign" travels as this word.
const ANY_CAMPAIGN = "any";

/** The same follow-up steps as Leads > Follow-ups (same data, same builder), for the Engage page.
 *  Viewing needs leads.view (the page's caller checks it); editing needs leads.manage. */
export default function FollowUpStepsSection({ canManage }: { canManage: boolean }) {
  const [trigger, setTrigger] = useState<"inbound" | "broadcast" | "campaign_reply">("inbound");
  const [templates, setTemplates] = useState<WabaTemplate[]>([]);
  const [broadcasts, setBroadcasts] = useState<BroadcastHistoryItem[]>([]);
  const [broadcastId, setBroadcastId] = useState("");

  useEffect(() => {
    api.templates
      .list()
      .then((rows) => setTemplates(rows.filter((t) => t.status === "APPROVED")))
      .catch(() => {});
    api.broadcasts.history().then(setBroadcasts).catch(() => {});
  }, []);

  const tab = (id: "inbound" | "broadcast" | "campaign_reply") =>
    `h-8 shrink-0 whitespace-nowrap rounded-xl px-3 text-xs sm:h-auto sm:px-4 sm:py-2 sm:text-sm ${trigger === id ? "bg-on-surface text-surface" : "bg-on-surface/10 text-on-surface"}`;

  return (
    <div className="space-y-6">
      <div className="flex flex-nowrap gap-2 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden sm:flex-wrap sm:overflow-visible">
        <button type="button" aria-pressed={trigger === "inbound"} onClick={() => setTrigger("inbound")} className={tab("inbound")}>
          Lead Reply Follow-up
        </button>
        <button type="button" aria-pressed={trigger === "broadcast"} onClick={() => setTrigger("broadcast")} className={tab("broadcast")}>
          Campaign Follow-up
        </button>
        <button type="button" aria-pressed={trigger === "campaign_reply"} onClick={() => setTrigger("campaign_reply")} className={tab("campaign_reply")}>
          Campaign reply, no order
        </button>
      </div>

      {(trigger === "broadcast" || trigger === "campaign_reply") && (
        <label className="block">
          <span className="font-label text-xs uppercase tracking-widest text-on-surface-muted">Broadcast</span>
          <Select
            value={trigger === "campaign_reply" && !broadcastId ? ANY_CAMPAIGN : broadcastId}
            onChange={(v) => setBroadcastId(v === ANY_CAMPAIGN ? "" : v)}
            placeholder="Select a broadcast…"
            className="mt-1 max-w-md"
            options={[
              ...(trigger === "campaign_reply" ? [{ value: ANY_CAMPAIGN, label: "Any campaign" }] : []),
              ...broadcasts
              .flatMap((b) => (b.broadcast_id ? [{ ...b, broadcast_id: b.broadcast_id }] : []))
              .map((b) => ({
                value: b.broadcast_id,
                label: `${b.template_name} · ${new Date(b.timestamp).toLocaleString()}`,
              })),
            ]}
          />
        </label>
      )}

      <ReengagementBuilder
        key={`${trigger}:${broadcastId}`}
        type={trigger}
        broadcastId={trigger === "inbound" ? undefined : broadcastId || undefined}
        templates={templates}
        canManage={canManage}
      />
    </div>
  );
}
