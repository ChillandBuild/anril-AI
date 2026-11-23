"use client";
import { useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { SwitchPill } from "@/components/ui/controls";
import { automationsApi, type EveningSummary } from "@/lib/automationsApi";

/** canManage: the on/off switch (settings.manage or templates.manage). canSubmit: sending the template to WhatsApp (the route needs settings.manage). */
export function EveningSummaryCard({ canManage, canSubmit, onChanged }: { canManage: boolean; canSubmit: boolean; onChanged: () => void }) {
  const { data, mutate } = useSWR<EveningSummary>("evening-summary", () => automationsApi.eveningSummary());
  const [busy, setBusy] = useState(false);

  async function toggle(on: boolean) {
    setBusy(true);
    try {
      await automationsApi.setEveningSummary(on);
      await mutate();
      onChanged();
    } catch (e) {
      toast.error(e instanceof Error && e.message ? e.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  async function submitTemplate() {
    setBusy(true);
    try {
      await automationsApi.submitEveningTemplate();
      toast.success("Sent to WhatsApp for approval.");
      await mutate();
      onChanged();
    } catch (e) {
      toast.error(e instanceof Error && e.message ? e.message : "Could not send it to WhatsApp.");
    } finally {
      setBusy(false);
    }
  }

  if (!data) return <div className="card h-24 animate-pulse rounded-3xl bg-border-subtle" />;
  const notSent = !data.template_status;

  return (
    <section className="card rounded-3xl p-4" aria-labelledby="evening-title">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 id="evening-title" className="font-label text-base font-bold text-ink">Evening summary</h2>
          <p className="mt-1 font-body text-sm text-[#556274]">
            A WhatsApp message to you at {data.sends_at} with your day: chats, new customers, orders and money in.
          </p>
        </div>
        <SwitchPill on={data.on} disabled={!canManage} loading={busy} aria-label="Evening summary" onChange={toggle} />
      </div>
      {data.note && (
        <p className="mt-3 rounded-xl border border-border-subtle bg-surface-subtle px-3 py-2 font-body text-sm text-ink">
          {data.note}. It will start by itself once WhatsApp says yes.
        </p>
      )}
      {notSent && canSubmit && (
        <button
          type="button"
          disabled={busy}
          onClick={submitTemplate}
          className="mt-3 min-h-10 rounded-xl border border-primary bg-primary px-4 font-label text-sm font-bold text-white disabled:opacity-60"
        >
          Send to WhatsApp for approval
        </button>
      )}
    </section>
  );
}
