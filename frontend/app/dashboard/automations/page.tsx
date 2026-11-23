"use client";
import { useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { automationsApi, type AutomationList, type AutomationRow } from "@/lib/automationsApi";
import { AutomationLine } from "@/components/automations/AutomationLine";
import { EveningSummaryCard } from "@/components/automations/EveningSummaryCard";
import { ComebackOfferCard } from "@/components/automations/ComebackOfferCard";

const OWN_PAGE_KINDS = new Set(["evening_summary", "comeback_offer"]);

export default function AutomationsPage() {
  const { role, permissions, loading: authLoading } = useAuthRole();
  const has = (p: string) => role === "owner" || permissions.includes(p);
  const canView = has("settings.view") || has("templates.view");
  const canManage = has("settings.manage") || has("templates.manage");
  // Sending the evening-summary template to WhatsApp (POST /automations/evening-summary/template) needs settings.manage alone.
  const canSubmit = has("settings.manage");

  const { data, error, isLoading, mutate } = useSWR<AutomationList>(canView ? "automation-list" : null, () => automationsApi.list(), {
    refreshInterval: 60000,
  });
  const [busyKey, setBusyKey] = useState<string | null>(null);

  async function toggle(row: AutomationRow, on: boolean) {
    setBusyKey(row.key);
    try {
      await automationsApi.toggle(row.key, on);
      await mutate();
    } catch (e) {
      toast.error(e instanceof Error && e.message ? e.message : "Could not change this automation.");
    } finally {
      setBusyKey(null);
    }
  }

  if (authLoading) return null;
  if (!canView) return <p className="font-body text-sm text-[#556274]">You do not have access to automations.</p>;

  const rows = (data?.automations ?? []).filter((a) => !OWN_PAGE_KINDS.has(a.kind));
  const paused = (data?.automations ?? []).filter((a) => a.paused || a.paused_reason);

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4">
      <header>
        <h1 className="font-label text-xl font-bold text-ink">Automations</h1>
        <p className="mt-1 font-body text-sm text-[#556274]">Messages Anril sends for you, without you pressing anything.</p>
      </header>

      {data && data.paused_count > 0 && (
        <div role="alert" className="rounded-2xl border border-red-300 bg-red-50 p-3 font-body text-sm text-red-900">
          <p className="font-bold">
            {data.paused_count === 1 ? "1 automation is paused" : `${data.paused_count} automations are paused`} because WhatsApp stopped a message.
          </p>
          <ul className="mt-1 list-disc pl-5">
            {paused.map((a) => <li key={a.key}>{a.name}{a.paused_reason ? `: ${a.paused_reason}` : ""}</li>)}
          </ul>
          <p className="mt-1">They start again by themselves when WhatsApp approves the message.</p>
        </div>
      )}

      {isLoading && <div className="card h-24 animate-pulse rounded-3xl bg-border-subtle" />}
      {error && !data && (
        <p role="alert" className="rounded-xl border border-border-subtle bg-surface-subtle px-3 py-2 font-body text-sm text-ink">
          Could not load your automations. Please refresh.
        </p>
      )}

      {data && rows.length > 0 && (
        <ul className="space-y-2" aria-label="Your automations">
          {rows.map((r) => <AutomationLine key={r.key} row={r} canManage={canManage} busy={busyKey === r.key} onToggle={toggle} />)}
        </ul>
      )}
      {data && rows.length === 0 && (
        <p className="font-body text-sm text-[#556274]">You have no automatic messages set up yet.</p>
      )}

      <EveningSummaryCard canManage={canManage} canSubmit={canSubmit} onChanged={() => void mutate()} />
      <ComebackOfferCard canManage={canManage} onChanged={() => void mutate()} />
    </div>
  );
}
