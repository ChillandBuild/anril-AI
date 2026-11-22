"use client";

import { useEffect, useState } from "react";
import { api, BroadcastHistoryItem, WabaTemplate } from "@/lib/api";
import { Select } from "@/components/ui/Select";
import ReengagementBuilder from "@/app/dashboard/leads/ReengagementBuilder";

/** The same follow-up steps as Leads > Follow-ups (same data, same builder), for the Engage page.
 *  Viewing needs leads.view (the page's caller checks it); editing needs leads.manage. */
export default function FollowUpStepsSection({ canManage }: { canManage: boolean }) {
  const [trigger, setTrigger] = useState<"inbound" | "broadcast">("inbound");
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

  const tab = (id: "inbound" | "broadcast") =>
    `rounded-xl px-4 py-2 text-sm ${trigger === id ? "bg-on-surface text-surface" : "bg-on-surface/10 text-on-surface"}`;

  return (
    <div className="space-y-6">
      <div className="flex gap-2">
        <button type="button" aria-pressed={trigger === "inbound"} onClick={() => setTrigger("inbound")} className={tab("inbound")}>
          Lead Reply Follow-up
        </button>
        <button type="button" aria-pressed={trigger === "broadcast"} onClick={() => setTrigger("broadcast")} className={tab("broadcast")}>
          Campaign Follow-up
        </button>
      </div>

      {trigger === "broadcast" && (
        <label className="block">
          <span className="font-label text-xs uppercase tracking-widest text-on-surface-muted">Broadcast</span>
          <Select
            value={broadcastId}
            onChange={setBroadcastId}
            placeholder="Select a broadcast…"
            className="mt-1 max-w-md"
            options={broadcasts
              .flatMap((b) => (b.broadcast_id ? [{ ...b, broadcast_id: b.broadcast_id }] : []))
              .map((b) => ({
                value: b.broadcast_id,
                label: `${b.template_name} · ${new Date(b.timestamp).toLocaleString()}`,
              }))}
          />
        </label>
      )}

      <ReengagementBuilder
        key={`${trigger}:${broadcastId}`}
        type={trigger}
        broadcastId={trigger === "broadcast" ? broadcastId || undefined : undefined}
        templates={templates}
        canManage={canManage}
      />
    </div>
  );
}
