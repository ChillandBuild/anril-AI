"use client";
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { CalendarClock, FilePlus2, FileText, ListChecks, Loader2, Plus, Settings2, ShoppingBag, X } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { WaFormLanguage } from "@/lib/api";
import { cn } from "@/lib/utils";
import { AiraLoader } from "@/components/AiraLoader";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { useWhatsappForms, useWhatsappFormsSetup } from "@/hooks/useApi";
import { useAuthRole } from "../contexts/AuthRoleContext";
import { CatalogueTabs } from "../catalog/CatalogueTabs";
import { SectionLoadGate } from "../settings/SettingsSection";
import { KIND_NAMES, LANGUAGE_CHIP, StatusChip } from "./shared";
import { StatsLine } from "./[id]/WhenToSend";

export default function FormsPage() {
  const { role, permissions } = useAuthRole();
  const canManage = role === "owner" || permissions.includes("services.manage") || permissions.includes("settings.manage");
  const { data, error, mutate } = useWhatsappForms();
  const { data: setup } = useWhatsappFormsSetup();
  const [creating, setCreating] = useState(false);

  if (error) {
    return (
      <div className="w-full pb-28">
        <CatalogueTabs />
        <SectionLoadGate state="error" onRetry={() => mutate()}>{null}</SectionLoadGate>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="w-full pb-28">
        <CatalogueTabs />
        <AiraLoader inline className="min-h-[50vh]" />
      </div>
    );
  }

  const services = data.services_form;
  const servicesLive = services.status.live && services.status.state !== "failed";

  return (
    <div className="w-full space-y-8 pb-28">
      <CatalogueTabs />

      <section aria-labelledby="services-form" className="rounded-2xl bg-surface px-5 py-5 ring-1 ring-surface-mid sm:px-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 max-w-2xl space-y-1.5">
            <div className="flex flex-wrap items-center gap-2.5">
              <h2 id="services-form" className="font-display text-lg font-bold text-ink">Services form</h2>
              {services.collect_with === "form" && services.selling_on ? (
                <StatusChip status={services.status} live={servicesLive} />
              ) : (
                <span className="rounded-full bg-surface-mid px-2.5 py-0.5 font-label text-[11px] font-semibold text-ink-secondary">
                  Not in use
                </span>
              )}
            </div>
            <p className="font-body text-sm leading-relaxed text-ink-secondary">
              Built from your Services packages, add-ons and details, and sent when a customer wants to book. It
              updates by itself when you save Services.
            </p>
            <StatsLine stats={services.stats} />
            {services.status.state === "failed" && services.status.error && (
              <p className="font-body text-xs text-amber-800">{services.status.error}</p>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            <Link
              href="/dashboard/services"
              className="inline-flex items-center gap-1.5 rounded-xl px-3 py-2 font-label text-xs font-semibold text-ink ring-1 ring-surface-mid hover:bg-surface-low"
            >
              <Settings2 size={14} /> {services.collect_with === "form" ? "Edit in Services" : "Turn on in Services"}
            </Link>
            <Link
              href="/dashboard/forms/services/answers"
              className="inline-flex items-center gap-1.5 rounded-xl px-3 py-2 font-label text-xs font-semibold text-ink ring-1 ring-surface-mid hover:bg-surface-low"
            >
              <ListChecks size={14} /> Answers <span className="tabular-nums text-ink-muted">{services.responses}</span>
            </Link>
          </div>
        </div>
      </section>

      <section aria-labelledby="own-forms" className="space-y-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 id="own-forms" className="font-display text-lg font-bold text-ink">Your forms</h2>
            <p className="font-body text-sm text-ink-secondary">
              Enquiries, appointments, feedback, admissions. Send one from any chat; the answers land on the customer.
            </p>
          </div>
          {canManage && (
            <button
              type="button"
              onClick={() => setCreating(true)}
              className="inline-flex items-center gap-1.5 rounded-xl bg-primary px-4 py-2 font-label text-sm font-semibold text-white shadow-sm hover:bg-primary-dark"
            >
              <Plus size={15} /> New form
            </button>
          )}
        </div>

        {data.forms.length === 0 ? (
          <div className="flex flex-col items-center gap-2 rounded-2xl border border-dashed border-surface-mid px-6 py-12 text-center">
            <FileText size={22} className="text-ink-muted" aria-hidden />
            <p className="font-label text-sm font-semibold text-ink">No forms yet</p>
            <p className="max-w-sm font-body text-xs text-ink-secondary">
              Start from a ready form in English, Tamil or Tanglish, then change every question and word.
            </p>
          </div>
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2">
            {data.forms.map((form) => (
              <li key={form.id} className="flex flex-col gap-3 rounded-2xl bg-surface p-4 ring-1 ring-surface-mid">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate font-label text-sm font-bold text-ink">{form.name}</p>
                    <p className="font-body text-xs text-ink-muted">
                      {LANGUAGE_CHIP[form.language]} ·{" "}
                      {form.kind === "order"
                        ? KIND_NAMES.order
                        : `${form.kind === "booking" ? `${KIND_NAMES.booking} · ` : ""}${form.fields.length} question${form.fields.length === 1 ? "" : "s"}`}
                    </p>
                  </div>
                  <StatusChip status={form.status} live={form.live} />
                </div>
                <StatsLine stats={form.stats} />
                {form.status.state === "failed" && form.status.error && (
                  <p className="font-body text-xs text-amber-800">{form.status.error}</p>
                )}
                <div className="mt-auto flex flex-wrap gap-2">
                  <Link
                    href={`/dashboard/forms/${form.id}`}
                    className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 font-label text-xs font-semibold text-primary-700 ring-1 ring-primary/20 hover:bg-primary-light/60"
                  >
                    {canManage ? "Edit" : "View"}
                  </Link>
                  <Link
                    href={`/dashboard/forms/${form.id}/answers`}
                    className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 font-label text-xs font-semibold text-ink ring-1 ring-surface-mid hover:bg-surface-low"
                  >
                    Answers <span className="tabular-nums text-ink-muted">{form.responses}</span>
                  </Link>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {creating && setup && <NewFormDialog setup={setup} onClose={() => setCreating(false)} />}
    </div>
  );
}

function NewFormDialog({ setup, onClose }: { setup: NonNullable<ReturnType<typeof useWhatsappFormsSetup>["data"]>; onClose: () => void }) {
  const router = useRouter();
  const [language, setLanguage] = useState<WaFormLanguage>("en");
  const [busy, setBusy] = useState<string | null>(null);

  async function create(starter: string | null) {
    setBusy(starter ?? "blank");
    try {
      const form = await api.whatsappForms.create({ starter, language });
      router.push(`/dashboard/forms/${form.id}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't create the form. Try again.");
      setBusy(null);
    }
  }

  return (
    <div className="fixed inset-0 z-dialog flex items-end justify-center bg-[#0A1528]/40 p-0 sm:items-center sm:p-4" role="dialog" aria-modal="true" aria-labelledby="new-form-title">
      <div className="w-full max-w-lg rounded-t-2xl bg-white p-5 shadow-xl sm:rounded-2xl" style={{ paddingBottom: "max(1.25rem, env(safe-area-inset-bottom, 0px))" }}>
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 id="new-form-title" className="font-display text-base font-bold text-ink">New form</h2>
            <p className="font-body text-xs text-ink-secondary">Pick a language and a starting point. You can change everything after.</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-lg p-1.5 text-ink-muted hover:bg-surface-mid">
            <X size={16} />
          </button>
        </div>
        <SegmentedControl
          className="mt-4"
          aria-label="Form language"
          value={language}
          onChange={(v) => setLanguage(v)}
          options={setup.languages.map((l) => ({ value: l.key, label: l.name }))}
        />
        <div className="mt-4 grid gap-2 sm:grid-cols-2">
          {[{ key: null as string | null, name: "Blank form", hint: "Start with no questions" },
            ...setup.starters.map((s) => ({ key: s.key as string | null, name: s.names[language], hint: "Ready questions" }))].map((option) => (
            <button
              key={option.key ?? "blank"}
              type="button"
              disabled={busy !== null}
              onClick={() => create(option.key)}
              className={cn(
                "flex items-center gap-3 rounded-xl px-3 py-3 text-left ring-1 ring-surface-mid transition-colors hover:bg-primary-light/40 hover:ring-primary/30 disabled:opacity-60",
              )}
            >
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary-light text-primary-700">
                {busy === (option.key ?? "blank") ? <Loader2 size={15} className="animate-spin" /> : option.key ? <FileText size={15} /> : <FilePlus2 size={15} />}
              </span>
              <span className="min-w-0">
                <span className="block truncate font-label text-sm font-semibold text-ink">{option.name}</span>
                <span className="block font-body text-[11px] text-ink-muted">{option.hint}</span>
              </span>
            </button>
          ))}
        </div>
        {(setup.live_kinds?.length ?? 0) > 0 && (
          <>
            <p className="mt-5 font-label text-[11px] font-semibold uppercase tracking-wider text-ink-muted">Live forms</p>
            <p className="font-body text-[11px] text-ink-secondary">They read your business while the customer fills them in.</p>
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              {(setup.live_kinds ?? []).map((live) => (
                <button
                  key={live.key}
                  type="button"
                  disabled={busy !== null}
                  onClick={() => create(live.key)}
                  className="flex items-center gap-3 rounded-xl px-3 py-3 text-left ring-1 ring-surface-mid transition-colors hover:bg-primary-light/40 hover:ring-primary/30 disabled:opacity-60"
                >
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary-light text-primary-700">
                    {busy === live.key ? <Loader2 size={15} className="animate-spin" /> : live.key === "order" ? <ShoppingBag size={15} /> : <CalendarClock size={15} />}
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate font-label text-sm font-semibold text-ink">{live.names[language]}</span>
                    <span className="block font-body text-[11px] text-ink-muted">
                      {live.key === "order" ? "Catalogue items with live price and stock" : "Only the times still free"}
                    </span>
                  </span>
                </button>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
