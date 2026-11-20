"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Loader2, Settings2, X } from "lucide-react";
import { api, type AdvanceRule, type OrderSettings } from "@/lib/api";
import { cn } from "@/lib/utils";

const STEP_NAMES = ["Working on it", "Stitching", "Packing", "Preparing", "Repairing", "Printing"];

/** Owner only: the shop's advance rule, the middle step's name, the Google review link. */
export function OrderSettingsDialog({ onClose, canEdit }: { onClose: () => void; canEdit: boolean }) {
  const [settings, setSettings] = useState<OrderSettings | null>(null);
  const [rule, setRule] = useState<AdvanceRule | null>(null);
  const [custom, setCustom] = useState("");
  const [valueText, setValueText] = useState("");
  const [minText, setMinText] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    Promise.all([api.orders.settings(), api.orders.advanceRule()]).then(([s, r]) => {
      setSettings(s);
      setRule(r);
      if (!STEP_NAMES.includes(s.working_label)) setCustom(s.working_label);
      setValueText(r.kind === "none" ? "" : String(r.value));
      setMinText(r.min_total_paise ? String(r.min_total_paise / 100) : "");
    }).catch(() => toast.error("Couldn't load the settings"));
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function save() {
    if (!settings || !rule) return;
    setSaving(true);
    try {
      const label = custom.trim() || settings.working_label;
      await api.orders.saveSettings({ working_label: label, google_review_link: settings.google_review_link.trim() });
      await api.orders.saveAdvanceRule({
        kind: rule.kind, value: rule.kind === "none" ? 0 : Number(valueText) || 0,
        min_total_paise: minText ? Math.round(Number(minText) * 100) : 0,
      });
      toast.success("Saved");
      onClose();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn't save");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-dialog flex items-center justify-center bg-stone-950/40 p-4 backdrop-blur-[2px]" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-labelledby="order-settings-title" onClick={(e) => e.stopPropagation()}
        className="max-h-[92vh] w-full max-w-lg overflow-y-auto rounded-3xl bg-white p-5 shadow-2xl sm:p-6">
        <div className="mb-4 flex items-center justify-between">
          <h2 id="order-settings-title" className="inline-flex items-center gap-2 font-display text-lg font-bold text-[#0A1528]"><Settings2 size={18} /> Order settings</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-lg p-1.5 text-[#94a3b8] hover:bg-stone-100"><X size={18} /></button>
        </div>
        {!settings || !rule ? (
          <div className="flex justify-center py-10"><Loader2 className="animate-spin text-primary" /></div>
        ) : (
          <>
          <fieldset disabled={!canEdit} className="space-y-5">
            <div>
              <p className="font-label text-xs font-bold text-[#0A1528]">Advance to ask for</p>
              <p className="text-xs text-on-surface-muted">Quotes and Deliver-later bills start from this. Staff can change it on one order; the order shows the change.</p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {(["none", "percent", "fixed"] as const).map((k) => (
                  <button key={k} type="button" onClick={() => setRule({ ...rule, kind: k })} aria-pressed={rule.kind === k}
                    className={cn("rounded-full border px-3 py-1.5 font-label text-xs font-bold", rule.kind === k ? "border-primary bg-primary-50 text-primary-800" : "border-[#e2e8f0] text-[#334155]")}>
                    {k === "none" ? "No advance" : k === "percent" ? "A percent" : "A fixed amount"}
                  </button>
                ))}
              </div>
              {rule.kind !== "none" && (
                <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
                  <input value={valueText} onChange={(e) => setValueText(e.target.value.replace(/[^\d.]/g, ""))} inputMode="decimal"
                    aria-label="Advance" placeholder={rule.kind === "percent" ? "30" : "1000"}
                    className="h-9 w-24 rounded-lg border border-[#e2e8f0] px-2.5 text-right tabular-nums focus:outline-none focus:ring-2 focus:ring-primary-200" />
                  <span className="text-on-surface-muted">{rule.kind === "percent" ? "% of the total" : "₹"}, only on orders above ₹</span>
                  <input value={minText} onChange={(e) => setMinText(e.target.value.replace(/[^\d.]/g, ""))} inputMode="decimal" aria-label="Only above"
                    placeholder="any" className="h-9 w-24 rounded-lg border border-[#e2e8f0] px-2.5 text-right tabular-nums focus:outline-none focus:ring-2 focus:ring-primary-200" />
                </div>
              )}
            </div>

            <div>
              <p className="font-label text-xs font-bold text-[#0A1528]">The &ldquo;working on it&rdquo; step</p>
              <p className="text-xs text-on-surface-muted">What your shop does between the order and Ready. It shows on every order.</p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {STEP_NAMES.map((n) => (
                  <button key={n} type="button" onClick={() => { setSettings({ ...settings, working_label: n }); setCustom(""); }}
                    aria-pressed={!custom && settings.working_label === n}
                    className={cn("rounded-full border px-3 py-1.5 font-label text-xs font-bold",
                      !custom && settings.working_label === n ? "border-primary bg-primary-50 text-primary-800" : "border-[#e2e8f0] text-[#334155]")}>
                    {n}
                  </button>
                ))}
                <input value={custom} onChange={(e) => setCustom(e.target.value)} maxLength={30} placeholder="Your own word" aria-label="Your own step name"
                  className="h-8 w-36 rounded-full border border-dashed border-[#cbd5e1] px-3 text-xs focus:outline-none focus:ring-2 focus:ring-primary-200" />
              </div>
            </div>

            <div>
              <label className="font-label text-xs font-bold text-[#0A1528]" htmlFor="review-link">Google review link</label>
              <p className="text-xs text-on-surface-muted">After a customer picks up or gets their order, the thank-you message asks for a review here.</p>
              <input id="review-link" value={settings.google_review_link} onChange={(e) => setSettings({ ...settings, google_review_link: e.target.value })}
                placeholder="https://g.page/r/…" maxLength={300}
                className="mt-2 h-10 w-full rounded-xl border border-[#e2e8f0] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary-200" />
            </div>
          </fieldset>
            <div className="mt-5 flex items-center justify-between gap-3 border-t border-[#eef2f6] pt-4">
              <span className="text-xs text-on-surface-muted">{canEdit ? "" : "Only the owner can change these."}</span>
              <div className="flex gap-2">
                <button type="button" onClick={onClose} className="rounded-xl border border-[#e2e8f0] px-4 py-2 font-label text-sm font-bold text-[#334155]">Close</button>
                {canEdit && (
                  <button type="button" onClick={save} disabled={saving}
                    className="inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2 font-label text-sm font-bold text-white disabled:opacity-50">
                    {saving && <Loader2 size={14} className="animate-spin" />} Save
                  </button>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
