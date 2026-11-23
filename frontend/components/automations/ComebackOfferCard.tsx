"use client";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { SwitchPill } from "@/components/ui/controls";
import { automationsApi, statusWords, type ComebackOffer } from "@/lib/automationsApi";

const inputCls = "min-h-10 w-full rounded-xl border border-border-subtle bg-white px-3 font-body text-sm text-ink disabled:opacity-60";

export function ComebackOfferCard({ canManage, onChanged }: { canManage: boolean; onChanged: () => void }) {
  const { data, mutate } = useSWR<ComebackOffer>("comeback-offer", () => automationsApi.comeback());
  const [template, setTemplate] = useState("");
  const [offer, setOffer] = useState("");
  const [code, setCode] = useState("");
  const [endsOn, setEndsOn] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!data) return;
    setTemplate(data.template_name ?? "");
    setOffer(data.offer);
    setCode(data.code);
    setEndsOn(data.ends_on ?? "");
  }, [data]);

  async function save(on: boolean) {
    setBusy(true);
    try {
      await automationsApi.setComeback({ on, template_name: template || null, offer, code, ends_on: endsOn || null });
      await mutate();
      onChanged();
      toast.success("Saved.");
    } catch (e) {
      toast.error(e instanceof Error && e.message ? e.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  if (!data) return <div className="card h-24 animate-pulse rounded-3xl bg-border-subtle" />;

  return (
    <section className="card rounded-3xl p-4" aria-labelledby="comeback-title">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 id="comeback-title" className="font-label text-base font-bold text-ink">Come-back offer</h2>
          <p className="mt-1 font-body text-sm text-[#556274]">
            Send an offer to customers who bought before but have not bought in 60 days. No one gets more than one a month.
          </p>
          <p className="mt-1 font-body text-sm font-bold text-ink">Cost: {data.cost_note}</p>
        </div>
        <SwitchPill
          on={data.on}
          disabled={!canManage || (!data.on && !template)}
          loading={busy}
          aria-label="Come-back offer"
          onChange={save}
        />
      </div>

      <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="font-body text-sm text-ink sm:col-span-2">
          Message to send
          <select className={`${inputCls} mt-1`} value={template} disabled={!canManage || busy} onChange={(e) => setTemplate(e.target.value)}>
            <option value="">Pick an approved message</option>
            {data.approved_templates.map((t) => <option key={t.name} value={t.name}>{t.name}</option>)}
          </select>
          {data.approved_templates.length === 0 && (
            <span className="mt-1 block text-xs text-[#556274]">No approved messages yet. Create one under Message templates and wait for WhatsApp to approve it.</span>
          )}
          {data.template_name && data.template_status && data.template_status !== "APPROVED" && (
            <span className="mt-1 block text-xs text-[#556274]">{statusWords(data.template_status)}</span>
          )}
        </label>
        <label className="font-body text-sm text-ink sm:col-span-2">
          The offer
          <input className={`${inputCls} mt-1`} value={offer} maxLength={400} disabled={!canManage || busy} placeholder="10% off your next order" onChange={(e) => setOffer(e.target.value)} />
        </label>
        <label className="font-body text-sm text-ink">
          Code (if any)
          <input className={`${inputCls} mt-1`} value={code} maxLength={60} disabled={!canManage || busy} onChange={(e) => setCode(e.target.value)} />
        </label>
        <label className="font-body text-sm text-ink">
          Offer ends on
          <input type="date" className={`${inputCls} mt-1`} value={endsOn} disabled={!canManage || busy} onChange={(e) => setEndsOn(e.target.value)} />
        </label>
      </div>

      {canManage && (
        <button
          type="button"
          disabled={busy}
          onClick={() => save(data.on)}
          className="mt-3 min-h-10 rounded-xl border border-primary bg-primary px-4 font-label text-sm font-bold text-white disabled:opacity-60"
        >
          Save offer
        </button>
      )}
    </section>
  );
}
