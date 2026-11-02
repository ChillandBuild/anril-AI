"use client";
import { useCallback, useEffect, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { API_URL, getAuthHeaders } from "@/lib/api";
import { SwitchPill } from "@/components/ui/controls";
import { ConflictsLink } from "@/components/brain/ConflictsLink";
import { useAuthRole } from "../contexts/AuthRoleContext";
import { CatalogueTabs } from "../catalog/CatalogueTabs";
import { SaveButton, SaveStatus, SectionLoadGate } from "../settings/SettingsSection";
import { AiraLoader } from "@/components/AiraLoader";
import { slugify } from "../settings/slugify";
import { PackageEditor, type IntakePackage } from "./PackageEditor";
import { chargePaise, gstPaise, GST_MAX, GST_MIN, parseGstPercent } from "./gst";

type FieldType = "text" | "date" | "choice";

interface IntakeField {
  key: string;
  label: string;
  type: FieldType;
  options?: string[];
}

// Everything Aira sells and collects in WhatsApp, in one config: this used to be
// split across a "Packages" page and a separate "Paid Intake" panel, which could
// save independently of each other and drift out of sync. `trigger_description`
// and `offer_message` are deliberately absent here -- they're dead fields (only
// the bypassed legacy route_intake ever read them); the backend still accepts
// them on PATCH for backward compatibility, we just never send them.
interface SellConfig {
  enabled: boolean;
  packages: IntakePackage[];
  fields: IntakeField[];
  service_noun: string;
  gst_percent: number;
}

const DEFAULT: SellConfig = {
  enabled: false,
  packages: [],
  fields: [],
  service_noun: "consultation",
  gst_percent: 0,
};

function toSellConfig(data: Record<string, unknown>): SellConfig {
  return {
    enabled: !!data.enabled,
    packages: (data.packages as IntakePackage[] | undefined) ?? [],
    fields: (data.fields as IntakeField[] | undefined) ?? [],
    service_noun: (data.service_noun as string | undefined) ?? "consultation",
    gst_percent: Number(data.gst_percent) || 0,
  };
}

export default function ServicesPage() {
  const { role, permissions } = useAuthRole();
  const canManageSettings = role === "owner" || permissions.includes("services.manage") || permissions.includes("settings.manage");
  const [saved, setSaved] = useState<SellConfig>(DEFAULT);
  const [draft, setDraft] = useState<SellConfig>(DEFAULT);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved">("idle");
  // A failed load leaves saved/draft at DEFAULT (packages: [], fields: []), and an
  // edit on top of that would be a real PATCH that replaces the tenant's actual
  // config with that empty state. Save stays disabled until the GET succeeds.
  const [loaded, setLoaded] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  // The GST box keeps its own text so half-typed values ("1.") and out-of-range entries can show an error.
  const [gstText, setGstText] = useState("0");

  const load = useCallback(async () => {
    setLoadFailed(false);
    try {
      const auth = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/settings/intake-config`, { headers: auth });
      if (res.ok) {
        const data = await res.json();
        const next = toSellConfig(data);
        setGstText(gstToText(next.gst_percent));
        setSaved(next);
        setDraft(next);
        setLoaded(true);
        setLoadFailed(false);
      } else {
        setLoadFailed(true);
      }
    } catch {
      setLoadFailed(true);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const isDirty = JSON.stringify(draft) !== JSON.stringify(saved);

  const gstError = parseGstPercent(gstText).error;

  function handleGstChange(text: string) {
    setGstText(text);
    setDraft({ ...draft, gst_percent: parseGstPercent(text).value });
  }

  async function handleSave() {
    if (!canManageSettings || !loaded || gstError) return;
    setSaveState("saving");
    setSaveError(null);
    try {
      const auth = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/settings/intake-config`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...auth },
        body: JSON.stringify(draft),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(typeof body?.detail === "string" ? body.detail : "Couldn't save. Please try again.");
      }
      const data = await res.json();
      const next = toSellConfig(data);
      setGstText(gstToText(next.gst_percent));
      setSaved(next);
      setDraft(next);
      setSaveState("saved");
      setTimeout(() => setSaveState("idle"), 2000);
    } catch (err: unknown) {
      setSaveError(err instanceof Error ? err.message : "Couldn't save. Please try again.");
      setSaveState("idle");
    }
  }

  function addField() {
    setDraft({
      ...draft,
      fields: [...draft.fields, { key: `field_${draft.fields.length + 1}`, label: "", type: "text" }],
    });
  }

  function updateField(index: number, patch: Partial<IntakeField>) {
    const fields = draft.fields.map((f, i) => (i === index ? { ...f, ...patch } : f));
    setDraft({ ...draft, fields });
  }

  function removeField(index: number) {
    setDraft({ ...draft, fields: draft.fields.filter((_, i) => i !== index) });
  }

  const summary = sellingSummary(draft);

  // Until the saved config arrives, show the loader rather than the DEFAULT form,
  // which would read as real settings ("Off", "No packages yet").
  if (!loaded) {
    return (
      <div className="mx-auto w-full max-w-5xl pb-28">
        <CatalogueTabs />
        {loadFailed ? (
          <SectionLoadGate state="error" onRetry={load}>{null}</SectionLoadGate>
        ) : (
          <AiraLoader inline className="min-h-[50vh]" />
        )}
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-5xl pb-28">
      <CatalogueTabs />
      <ConflictsLink />

      <section aria-labelledby="sell-heading" className="mt-6 flex flex-wrap items-start justify-between gap-x-8 gap-y-4 rounded-2xl bg-surface px-5 py-5 shadow-[0_1px_0_rgba(28,25,23,0.04)] ring-1 ring-surface-mid sm:px-6">
        <div className="min-w-0 max-w-2xl space-y-1.5">
          <div className="flex flex-wrap items-center gap-2.5">
            <h2 id="sell-heading" className="font-display text-lg font-bold text-ink">Sell in chat</h2>
            <span
              className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 font-label text-[11px] font-semibold uppercase tracking-wider ${
                draft.enabled ? "bg-emerald-50 text-emerald-700" : "bg-surface-mid text-ink-secondary"
              }`}
            >
              <span className={`h-1.5 w-1.5 rounded-full ${draft.enabled ? "bg-emerald-500" : "bg-ink-muted"}`} aria-hidden />
              {draft.enabled ? "Live" : "Off"}
            </span>
          </div>
          <p className="font-body text-sm leading-relaxed text-ink-secondary">
            Anril offers your packages as buttons, answers questions in between, collects the details
            below in any order, and sends the Razorpay link once every detail is in. Prices come only
            from this page.
          </p>
          <p className="font-body text-xs text-ink-muted tabular-nums">{summary}</p>
        </div>
        <div className="pt-1">
          <SwitchPill
            on={draft.enabled}
            disabled={!canManageSettings}
            onChange={(v) => setDraft({ ...draft, enabled: v })}
            aria-label="Let Anril sell these in chat"
          />
        </div>
      </section>

      <Row
        title="Packages"
        help="What Anril offers, at exactly these prices. Group options under one package (Long Term: 1 Year, 2 Year) and add optional add-ons to any package."
      >
        <PackageEditor
          packages={draft.packages}
          onChange={(packages) => setDraft({ ...draft, packages })}
          canManage={canManageSettings}
        />
      </Row>

      <Row
        title="GST"
        help="One rate for everything you sell. It is added on top of the package price."
      >
        <GstInput
          text={gstText}
          error={gstError}
          pct={draft.gst_percent}
          packages={draft.packages}
          canManage={canManageSettings}
          onChange={handleGstChange}
        />
      </Row>

      <Row
        title="Details to collect"
        help="Asked naturally in the chat, in any order. The payment link goes out only when all of them are in. Applies to every package."
        action={
          canManageSettings ? (
            <button
              type="button"
              onClick={addField}
              className="inline-flex items-center gap-1 rounded-lg px-2 py-1 font-label text-xs font-semibold text-primary-600 hover:bg-primary-light/60 hover:text-primary-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
            >
              <Plus size={14} /> Add detail
            </button>
          ) : null
        }
      >
        {draft.fields.length === 0 ? (
          <p className="font-body text-sm text-ink-muted">
            None. Anril sends the payment link as soon as the customer picks a package.
          </p>
        ) : (
          <ol className="divide-y divide-surface-mid rounded-xl ring-1 ring-surface-mid">
            {draft.fields.map((field, index) => (
              <li key={index} className="space-y-2 bg-surface px-3 py-3 first:rounded-t-xl last:rounded-b-xl">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="w-5 shrink-0 text-center font-label text-xs font-semibold text-ink-muted tabular-nums">{index + 1}</span>
                  <input
                    type="text"
                    aria-label={`Detail ${index + 1} name`}
                    placeholder="e.g. Date of birth"
                    value={field.label}
                    onChange={(e) => updateField(index, { label: e.target.value, key: slugify(e.target.value) })}
                    disabled={!canManageSettings}
                    className="min-w-0 flex-1 rounded-lg border border-transparent bg-surface-low px-3 py-1.5 font-body text-sm text-ink focus:border-primary/40 focus:bg-white focus:outline-none"
                  />
                  <select
                    aria-label={`Detail ${index + 1} type`}
                    value={field.type}
                    onChange={(e) => updateField(index, { type: e.target.value as FieldType })}
                    disabled={!canManageSettings}
                    className="rounded-lg border border-transparent bg-surface-low px-2.5 py-1.5 font-body text-sm text-ink focus:border-primary/40 focus:outline-none"
                  >
                    <option value="text">Text</option>
                    <option value="date">Date</option>
                    <option value="choice">Choice</option>
                  </select>
                  {canManageSettings && (
                    <button
                      type="button"
                      aria-label={`Remove detail ${index + 1}`}
                      onClick={() => removeField(index)}
                      className="rounded-lg p-1.5 text-ink-muted hover:bg-red-50 hover:text-red-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-300"
                    >
                      <Trash2 size={15} />
                    </button>
                  )}
                </div>
                {field.type === "choice" && (
                  <div className="pl-7">
                    <input
                      type="text"
                      aria-label={`Detail ${index + 1} options`}
                      placeholder="Options, comma separated: Morning, Afternoon, Evening"
                      value={(field.options ?? []).join(", ")}
                      onChange={(e) =>
                        updateField(index, {
                          options: e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
                        })
                      }
                      disabled={!canManageSettings}
                      className="w-full rounded-lg border border-transparent bg-surface-low px-3 py-1.5 font-body text-sm text-ink focus:border-primary/40 focus:bg-white focus:outline-none"
                    />
                    <p className="mt-1 font-body text-[11px] text-ink-muted">Anril shows these as buttons when it asks.</p>
                  </div>
                )}
              </li>
            ))}
          </ol>
        )}
      </Row>

      <Row
        title="What you call it"
        help="The word Anril and the payment receipt use for what you sell: consultation, reading, session, class."
      >
        <input
          type="text"
          aria-label="What you call it"
          value={draft.service_noun}
          onChange={(e) => setDraft({ ...draft, service_noun: e.target.value })}
          disabled={!canManageSettings}
          className="w-full max-w-sm rounded-lg border border-surface-mid bg-surface px-3 py-2 font-body text-sm text-ink focus:border-primary/40 focus:outline-none focus:ring-2 focus:ring-primary/15"
        />
      </Row>

      <div className="sticky bottom-0 z-10 -mx-4 mt-8 border-t border-surface-mid bg-surface-low/95 px-4 py-3 backdrop-blur supports-[backdrop-filter]:bg-surface-low/80 sm:mx-0 sm:rounded-2xl sm:border sm:px-5" style={{ paddingBottom: "max(0.75rem, env(safe-area-inset-bottom, 0px))" }}>
        <div className="flex flex-wrap items-center justify-between gap-3" aria-live="polite">
          {loadFailed || saveError ? (
            <span className="font-body text-xs font-semibold text-red-600">
              {loadFailed ? "Couldn't load your services. Reload the page before editing." : saveError}
            </span>
          ) : (
            <SaveStatus state={saveState} dirty={isDirty} idleLabel={isDirty ? "Unsaved changes" : "All changes saved"} />
          )}
          <SaveButton state={saveState} dirty={isDirty} disabled={!canManageSettings || !loaded || !!gstError} onClick={handleSave} />
        </div>
      </div>
    </div>
  );
}

function Row({
  title,
  help,
  action,
  children,
}: {
  title: string;
  help: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="grid gap-4 border-b border-surface-mid py-8 md:grid-cols-[minmax(0,15rem)_minmax(0,1fr)] md:gap-10">
      <div className="space-y-1.5">
        <div className="flex items-center justify-between gap-2 md:block">
          <h2 className="font-display text-base font-bold text-ink">{title}</h2>
          {action && <div className="md:hidden">{action}</div>}
        </div>
        <p className="font-body text-xs leading-relaxed text-ink-secondary">{help}</p>
        {action && <div className="hidden pt-1 md:-ml-2 md:block">{action}</div>}
      </div>
      <div className="min-w-0">{children}</div>
    </section>
  );
}

function gstToText(pct: number): string {
  return String(pct);
}

function GstInput({
  text, error, pct, packages, canManage, onChange,
}: {
  text: string; error: string | null; pct: number; packages: IntakePackage[]; canManage: boolean;
  onChange: (text: string) => void;
}) {
  const price = leafPrices(packages)[0];
  const showPreview = !error && pct > 0 && price !== undefined;
  return (
    <div className="space-y-2">
      <label className="block font-label text-xs font-semibold text-ink" htmlFor="gst-percent">
        GST added on top (%)
      </label>
      <input
        id="gst-percent"
        type="number"
        min={GST_MIN}
        max={GST_MAX}
        step={0.5}
        inputMode="decimal"
        value={text}
        onChange={(e) => onChange(e.target.value)}
        disabled={!canManage}
        aria-invalid={!!error}
        className="w-28 rounded-lg border border-surface-mid bg-surface px-3 py-2 font-body text-sm text-ink focus:border-primary/40 focus:outline-none focus:ring-2 focus:ring-primary/15"
      />
      <p className="font-body text-xs text-ink-secondary">
        Leave at 0 for no GST. Customers pay the package price plus this GST. Example: 18 for services.
      </p>
      {error && <p className="font-body text-xs font-semibold text-red-600">{error}</p>}
      {showPreview && (
        <p className="font-body text-xs text-ink-muted tabular-nums">
          {rupees(price)} → customer pays {rupees(chargePaise(price, pct))} ({rupees(gstPaise(price, pct))} GST)
        </p>
      )}
    </div>
  );
}

function leafPrices(packages: IntakePackage[]): number[] {
  return packages
    .filter((p) => p.active !== false)
    .flatMap((p) => (p.options && p.options.length ? leafPrices(p.options) : [p.amount_paise]))
    .filter((v) => v > 0);
}

function rupees(paise: number): string {
  return `₹${(paise / 100).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

function sellingSummary(config: SellConfig): string {
  const prices = leafPrices(config.packages);
  const count = prices.length;
  const range =
    count === 0 ? "no prices yet" : Math.min(...prices) === Math.max(...prices)
      ? rupees(prices[0])
      : `${rupees(Math.min(...prices))} – ${rupees(Math.max(...prices))}`;
  const details = config.fields.length;
  const gst = config.gst_percent > 0 ? ` + ${config.gst_percent}% GST` : "";
  return `${count} package${count === 1 ? "" : "s"} · ${range}${gst} · ${details} detail${details === 1 ? "" : "s"} before payment`;
}
