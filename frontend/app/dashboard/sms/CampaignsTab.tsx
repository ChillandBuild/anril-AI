"use client";

import { useState } from "react";
import useSWR from "swr";
import { Plus } from "lucide-react";
import { api } from "@/lib/api";
import { CampaignComposer } from "./CampaignComposer";
import { CampaignDetail } from "./CampaignDetail";
import { campaignStatusLabel, campaignStatusTone, formatCount, formatIst, formatRupees, friendlyError } from "./helpers";
import { Badge, Btn, Card, CardHeader, Empty, LoadError, Skeleton } from "./ui";
import { usePerm } from "./usePerm";

type View = { kind: "list" } | { kind: "new" } | { kind: "detail"; id: string };

export function CampaignsTab({ onBalanceChanged }: { onBalanceChanged: () => void }) {
  const { canManage } = usePerm();
  const [view, setView] = useState<View>({ kind: "list" });
  const campaigns = useSWR("sms:campaigns", () => api.sms.campaigns(50, 0), {
    refreshInterval: (d) => (d?.campaigns.some((c) => c.status === "sending" || c.status === "scheduled") ? 15_000 : 0),
  });

  if (view.kind === "new") {
    return (
      <CampaignComposer
        onClose={() => setView({ kind: "list" })}
        onCreated={(c) => {
          void campaigns.mutate();
          onBalanceChanged();
          setView({ kind: "detail", id: c.id });
        }}
      />
    );
  }

  if (view.kind === "detail") {
    return (
      <CampaignDetail
        id={view.id}
        onBack={() => setView({ kind: "list" })}
        onChanged={() => {
          void campaigns.mutate();
          onBalanceChanged();
        }}
      />
    );
  }

  const list = campaigns.data?.campaigns ?? [];

  return (
    <Card>
      <CardHeader
        title="Campaigns"
        hint="Every SMS you send to a group of leads."
        action={
          canManage ? (
            <Btn onClick={() => setView({ kind: "new" })}>
              <Plus size={15} /> New campaign
            </Btn>
          ) : undefined
        }
      />
      {campaigns.isLoading && !campaigns.data ? (
        <Skeleton className="m-4 h-40" />
      ) : campaigns.error && !campaigns.data ? (
        <LoadError message={friendlyError(campaigns.error, "Check your connection.")} onRetry={() => void campaigns.mutate()} />
      ) : list.length === 0 ? (
        <Empty
          title="No campaigns yet."
          hint={canManage ? "Start with New campaign: pick leads, pick a template, preview and send." : "Campaigns created by your team will show up here."}
        />
      ) : (
        <ul className="divide-y divide-[#f1f5f9]">
          {list.map((c) => (
            <li key={c.id}>
              <button
                type="button"
                onClick={() => setView({ kind: "detail", id: c.id })}
                className="block w-full px-4 py-3.5 text-left hover:bg-[#f8fafc] sm:px-5"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="min-w-0 break-words text-sm font-bold text-[#0A1528]">{c.name}</p>
                  <Badge tone={campaignStatusTone(c.status)}>{campaignStatusLabel(c.status)}</Badge>
                </div>
                <p className="mt-0.5 text-xs text-[#64748b]">
                  {c.status === "scheduled" && c.send_at ? `Goes out ${formatIst(c.send_at)} IST` : formatIst(c.created_at)} · Sender {c.sender_id}
                </p>
                <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-[#475569]">
                  <span>{formatCount(c.total)} total</span>
                  <span>{formatCount(c.counts.queued + c.counts.sending)} waiting</span>
                  <span>{formatCount(c.counts.submitted)} sent</span>
                  <span className="text-[#15803d]">{formatCount(c.counts.delivered)} delivered</span>
                  <span className="text-[#be123c]">{formatCount(c.counts.failed)} failed</span>
                  {c.counts.unknown > 0 && <span className="text-[#b45309]">{formatCount(c.counts.unknown)} checking…</span>}
                  <span className="font-semibold">Charged {formatRupees(c.charged_total)}</span>
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
