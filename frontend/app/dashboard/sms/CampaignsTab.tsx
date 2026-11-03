"use client";

import { useState } from "react";
import useSWR from "swr";
import { CheckCircle2, Circle } from "lucide-react";
import { api } from "@/lib/api";
import { CampaignDetail } from "./CampaignDetail";
import {
  campaignNeedsUpdates,
  campaignStatusLabel,
  campaignStatusTone,
  formatCount,
  formatIst,
  formatRupees,
  friendlyError,
  setupComplete,
  setupSteps,
} from "./helpers";
import { Badge, Btn, Card, CardHeader, Empty, LoadError, Skeleton } from "./ui";
import { usePerm } from "./usePerm";

type View = { kind: "list" } | { kind: "detail"; id: string };

export function CampaignsTab({ onBalanceChanged, onOpenTemplates }: { onBalanceChanged: () => void; onOpenTemplates: () => void }) {
  const { canManage } = usePerm();
  const [view, setView] = useState<View>({ kind: "list" });
  const [offset, setOffset] = useState(0);
  const status = useSWR("sms:status", () => api.sms.status(), { revalidateOnFocus: false });
  const balance = useSWR("sms:balance", () => api.sms.balance(), { revalidateOnFocus: true, shouldRetryOnError: false });
  const campaigns = useSWR(["sms:campaigns", offset], () => api.sms.campaigns(51, offset), {
    refreshInterval: (d) => (d?.campaigns.some(campaignNeedsUpdates) ? 15_000 : 0),
  });

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

  const fetched = campaigns.data?.campaigns ?? [];
  const list = fetched.slice(0, 50);
  const steps = setupSteps({
    templatesReady: status.data?.templates_ready === true,
    peTm: status.data?.checklist.pe_tm === true,
    smsCount: balance.data?.sms_count,
  });
  const showSetup = !!status.data && !(balance.isLoading && !balance.data) && !setupComplete(steps);

  return (
    <Card>
      <CardHeader
        title="Campaigns"
        hint="Every SMS you have sent or scheduled."
      />
      {campaigns.isLoading && !campaigns.data ? (
        <Skeleton className="m-4 h-40" />
      ) : campaigns.error && !campaigns.data ? (
        <LoadError message={friendlyError(campaigns.error, "Check your connection.")} onRetry={() => void campaigns.mutate()} />
      ) : list.length === 0 && showSetup ? (
        <div className="space-y-4 p-4 sm:p-5">
          <div>
            <h3 className="font-display text-base font-bold text-[#0A1528]">Get ready to send SMS</h3>
            <p className="mt-0.5 text-xs text-[#64748b]">You can send your first SMS once these are done.</p>
          </div>
          <ul className="space-y-2.5">
            {steps.map((step) => (
              <li key={step.key} className="flex items-start gap-2.5 text-sm">
                {step.done ? <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-success" /> : <Circle size={18} className="mt-0.5 shrink-0 text-[#cbd5e1]" />}
                <span className="min-w-0">
                  <span className={step.done ? "font-semibold text-[#0A1528]" : "text-[#64748b]"}>{step.label}</span>
                  {step.hint && (
                    <span className="block text-xs text-[#64748b]">
                      {step.key === "templates" && !step.done ? (
                        <button type="button" onClick={onOpenTemplates} className="font-bold text-primary hover:underline">{step.hint}</button>
                      ) : (
                        step.hint
                      )}
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ul>
          <p className="border-t border-[#f1f5f9] pt-3 text-xs text-[#64748b]">SMS help: {status.data?.support_contact || "contact your Anril account manager"}</p>
        </div>
      ) : list.length === 0 ? (
        <Empty
          title="No campaigns yet."
          hint={canManage ? "Go to Send SMS to send your first one." : "Campaigns created by your team will show up here."}
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
                  {c.amount_debited != null && <span className="text-[#64748b]">· {formatRupees(c.amount_debited)}</span>}
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
      {(offset > 0 || fetched.length > 50) && <div className="flex items-center justify-between gap-2 border-t border-border px-4 py-3 text-xs text-ink-muted">
        <span>Page {Math.floor(offset / 50) + 1}</span>
        <div className="flex gap-2">
          <Btn variant="outline" disabled={offset === 0} onClick={() => setOffset((current) => Math.max(0, current - 50))}>Previous</Btn>
          <Btn variant="outline" disabled={fetched.length <= 50} onClick={() => setOffset((current) => current + 50)}>Next</Btn>
        </div>
      </div>}
    </Card>
  );
}
