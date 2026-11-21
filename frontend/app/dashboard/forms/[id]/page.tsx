"use client";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ArrowDown, ArrowLeft, ArrowUp, ListChecks, Loader2, Plus, Send, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type {
  WaFormDesign, WaFormField, WaFormFieldType, WaFormKind, WaFormLanguage, WaFormSettings, WaFormSetup, WaFormTriggers,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { AiraLoader } from "@/components/AiraLoader";
import { Select } from "@/components/ui/Select";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { SwitchPill } from "@/components/ui/controls";
import { useWhatsappForm, useWhatsappFormsSetup } from "@/hooks/useApi";
import { useAuthRole } from "../../contexts/AuthRoleContext";
import { CatalogueTabs } from "../../catalog/CatalogueTabs";
import { SectionLoadGate } from "../../settings/SettingsSection";
import {
  CHOICE_TYPES, FIELD_TYPE_LABELS, FormPhonePreview, FormTextsEditor, KIND_NAMES, LiveFormPhonePreview, StatusChip,
  effectiveText, shownLength, textKeysFor,
} from "../shared";
import { BookingSettingsEditor, OrderSettingsEditor, bookingProblems } from "./LiveSettings";
import { StatsLine, WhenToSend } from "./WhenToSend";

interface Draft {
  name: string;
  language: WaFormLanguage;
  fields: WaFormField[];
  texts: Record<string, string>;
  triggers: WaFormTriggers;
  settings: WaFormSettings;
}

function toDraft(design: WaFormDesign): Draft {
  return {
    name: design.name,
    language: design.language,
    fields: design.fields.map((f) => ({ ...f, options: f.options ?? [] })),
    texts: { ...design.texts },
    triggers: JSON.parse(JSON.stringify(design.triggers)) as WaFormTriggers,
    settings: JSON.parse(JSON.stringify(design.settings ?? {})) as WaFormSettings,
  };
}

function newKey(fields: WaFormField[]): string {
  let n = fields.length + 1;
  while (fields.some((f) => f.key === `q${n}`)) n += 1;
  return `q${n}`;
}

/** What WhatsApp can't show, checked as you type (the server checks again on Save). */
function localProblems(draft: Draft, setup: WaFormSetup, kind: WaFormKind): string[] {
  const out: string[] = [];
  if (!draft.name.trim()) out.push("Give the form a name.");
  if (kind === "standard" && draft.fields.length === 0) out.push("Add at least one question.");
  if (kind === "booking") out.push(...bookingProblems(draft.settings));
  const fields = kind === "order" ? [] : draft.fields; // an order form asks nothing extra
  const seen = new Set<string>();
  for (const f of fields) {
    const label = f.label.trim().toLowerCase();
    if (label && seen.has(label)) out.push(`Two questions both say "${f.label.trim()}". Make them different.`);
    seen.add(label);
  }
  fields.forEach((f, i) => {
    const label = f.label.trim();
    if (!label) out.push(`Question ${i + 1} needs a question.`);
    else if (label.length > setup.label_limits[f.type]) out.push(`Question ${i + 1} is too long.`);
    if (CHOICE_TYPES.includes(f.type)) {
      const options = f.options.map((o) => o.trim()).filter(Boolean);
      const min = f.type === "dropdown" ? 1 : 2;
      if (options.length < min) out.push(`Question ${i + 1} needs at least ${min} options.`);
      if (new Set(options.map((o) => o.toLowerCase())).size !== options.length) out.push(`Question ${i + 1} has the same option twice.`);
      if (options.some((o) => o.length > setup.option_limit)) out.push(`An option in question ${i + 1} is too long.`);
    }
  });
  if (draft.triggers.ai.enabled && !draft.triggers.ai.when.trim()) out.push("Tell Anril when to send this form.");
  if (draft.triggers.ai.when.length > 300) out.push("The “send it when” line is too long.");
  if (draft.triggers.broadcasts.enabled && draft.triggers.broadcasts.templates.length === 0) out.push("Pick at least one broadcast template.");
  for (const key of textKeysFor(kind)) {
    const value = effectiveText(setup, draft.language, draft.texts, key);
    if (shownLength(key, value) > (setup.text_limits[key] ?? 1000)) out.push("One of the texts on the form is too long.");
  }
  return Array.from(new Set(out));
}

export default function FormBuilderPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { role, permissions } = useAuthRole();
  const canManage = role === "owner" || permissions.includes("services.manage") || permissions.includes("settings.manage");
  const { data: design, error, mutate } = useWhatsappForm(id);
  const { data: setup, error: setupError } = useWhatsappFormsSetup();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState<"save" | "publish" | null>(null);
  const [confirmArchive, setConfirmArchive] = useState(false);

  useEffect(() => {
    if (design && !draft) setDraft(toDraft(design));
  }, [design, draft]);

  const saved = useMemo(() => (design ? toDraft(design) : null), [design]);
  const dirty = Boolean(draft && saved && JSON.stringify(draft) !== JSON.stringify(saved));
  const kind: WaFormKind = design?.kind ?? "standard";
  const problems = draft && setup ? localProblems(draft, setup, kind) : [];

  // Leaving with unsaved changes asks first.
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  if (error || setupError) {
    return (
      <div className="mx-auto w-full max-w-6xl pb-28">
        <CatalogueTabs />
        <SectionLoadGate state="error" onRetry={() => mutate()}>{null}</SectionLoadGate>
      </div>
    );
  }
  if (!design || !setup || !draft) {
    return (
      <div className="mx-auto w-full max-w-6xl pb-28">
        <CatalogueTabs />
        <AiraLoader inline className="min-h-[50vh]" />
      </div>
    );
  }

  const textKeys = textKeysFor(kind);
  const words = Object.fromEntries(textKeys.map((k) => [k, effectiveText(setup, draft.language, draft.texts, k)]));

  function update(patch: Partial<Draft>) {
    setDraft((d) => (d ? { ...d, ...patch } : d));
  }
  function updateField(index: number, patch: Partial<WaFormField>) {
    update({ fields: draft!.fields.map((f, i) => (i === index ? { ...f, ...patch } : f)) });
  }
  function moveField(index: number, by: number) {
    const fields = [...draft!.fields];
    const [item] = fields.splice(index, 1);
    fields.splice(index + by, 0, item);
    update({ fields });
  }
  function addField() {
    update({ fields: [...draft!.fields, { key: newKey(draft!.fields), type: "text", label: "", required: true, options: [] }] });
  }

  async function persist(): Promise<WaFormDesign | null> {
    try {
      const next = await api.whatsappForms.save(id, {
        name: draft!.name.trim(), language: draft!.language,
        fields: kind === "order" ? [] : draft!.fields.map((f) => ({ ...f, label: f.label.trim(), options: CHOICE_TYPES.includes(f.type) ? f.options.map((o) => o.trim()).filter(Boolean) : [] })),
        texts: draft!.texts,
        triggers: draft!.triggers,
        settings: draft!.settings,
      });
      await mutate(next, { revalidate: false });
      setDraft(toDraft(next));
      return next;
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't save. Try again.");
      return null;
    }
  }

  async function handleSave() {
    setSaving("save");
    const next = await persist();
    if (next) toast.success(next.status.live ? "Saved. Publish to send the changes to WhatsApp." : "Saved.");
    setSaving(null);
  }

  async function handlePublish() {
    setSaving("publish");
    try {
      if (dirty && !(await persist())) return;
      const next = await api.whatsappForms.publish(id);
      await mutate(next, { revalidate: false });
      if (next.status.state === "failed") toast.error(next.status.error || "WhatsApp didn't accept the form.");
      else toast.success("Published. You can send it from any chat now.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't publish. Try again.");
    } finally {
      setSaving(null);
    }
  }

  async function handleArchive() {
    try {
      await api.whatsappForms.archive(id);
      toast.success("Form archived. Its answers are kept.");
      router.push("/dashboard/forms");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't archive. Try again.");
    }
  }

  const statusLine = dirty
    ? "Unsaved changes"
    : design.status.state === "failed"
      ? design.status.error || "WhatsApp didn't accept the form."
      : design.live
        ? "Saved and live on WhatsApp"
        : design.status.live
          ? "Saved. Publish to send these changes to WhatsApp."
          : "Saved. Publish to use it on WhatsApp.";

  return (
    <div className="mx-auto w-full max-w-6xl pb-28">
      <CatalogueTabs />
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <Link href="/dashboard/forms" className="inline-flex items-center gap-1.5 font-label text-xs font-semibold text-ink-secondary hover:text-ink">
          <ArrowLeft size={14} /> All forms
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <StatsLine stats={design.stats} />
          <StatusChip status={design.status} live={design.live} />
          <Link
            href={`/dashboard/forms/${id}/answers`}
            className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 font-label text-xs font-semibold text-ink ring-1 ring-surface-mid hover:bg-surface-low"
          >
            <ListChecks size={13} /> Answers <span className="tabular-nums text-ink-muted">{design.responses}</span>
          </Link>
        </div>
      </div>

      <div className="mt-5 grid gap-8 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="min-w-0 space-y-8">
          <section className="space-y-4 rounded-2xl bg-surface p-5 ring-1 ring-surface-mid">
            <label className="block space-y-1.5">
              <span className="font-label text-xs font-semibold text-ink">Form name</span>
              <input
                value={draft.name}
                maxLength={120}
                disabled={!canManage}
                onChange={(e) => update({ name: e.target.value })}
                placeholder="e.g. Site visit booking"
                className="w-full rounded-lg border border-surface-mid bg-surface px-3 py-2 font-body text-sm text-ink focus:border-primary/40 focus:outline-none focus:ring-2 focus:ring-primary/15"
              />
              <span className="block font-body text-[11px] text-ink-muted">Only you and your team see this name.</span>
            </label>
            <div className="space-y-1.5">
              <span className="font-label text-xs font-semibold text-ink">Language customers see</span>
              <SegmentedControl
                aria-label="Form language"
                value={draft.language}
                disabled={!canManage}
                onChange={(v) => update({ language: v })}
                options={setup.languages.map((l) => ({ value: l.key, label: l.name }))}
              />
              <p className="font-body text-[11px] text-ink-muted">
                Changes the buttons and titles you haven&apos;t edited. Your questions stay as you wrote them.
              </p>
            </div>
          </section>

          {kind !== "standard" && (
            <section aria-labelledby="live-settings" className="space-y-3">
              <div>
                <h2 id="live-settings" className="font-display text-base font-bold text-ink">{KIND_NAMES[kind]}</h2>
                <p className="font-body text-xs text-ink-secondary">
                  {kind === "order"
                    ? "Customers search your Catalogue, tick products and pick how many. Prices and stock are read the moment they open it; after they submit, Anril sends the payment link."
                    : "Customers see only the days and times still free, from the hours below. Two people can never book the same last place."}
                </p>
              </div>
              {kind === "order" ? (
                <OrderSettingsEditor settings={draft.settings} disabled={!canManage} onChange={(settings) => update({ settings })} />
              ) : (
                <BookingSettingsEditor settings={draft.settings} disabled={!canManage} onChange={(settings) => update({ settings })} />
              )}
            </section>
          )}

          {kind !== "order" && (
          <section aria-labelledby="questions" className="space-y-3">
            <div className="flex items-end justify-between gap-3">
              <div>
                <h2 id="questions" className="font-display text-base font-bold text-ink">
                  {kind === "booking" ? "Questions after they pick a time" : "Questions"}
                </h2>
                <p className="font-body text-xs text-ink-secondary">
                  {kind === "booking" ? "Optional. " : ""}Write them in any language or script. {draft.fields.length}/{setup.max_fields}
                </p>
              </div>
            </div>
            <ol className="space-y-3">
              {draft.fields.map((field, index) => {
                const limit = setup.label_limits[field.type];
                const over = field.label.trim().length > limit;
                const isChoice = CHOICE_TYPES.includes(field.type);
                return (
                  <li key={`${field.key}-${index}`} className="space-y-3 rounded-2xl bg-surface p-4 ring-1 ring-surface-mid">
                    <div className="flex flex-wrap items-start gap-2">
                      <span className="mt-2 w-5 shrink-0 text-center font-label text-xs font-semibold text-ink-muted tabular-nums">{index + 1}</span>
                      <div className="min-w-0 flex-1 space-y-1">
                        <input
                          aria-label={`Question ${index + 1}`}
                          value={field.label}
                          disabled={!canManage}
                          onChange={(e) => updateField(index, { label: e.target.value })}
                          placeholder="Type the question"
                          className={cn(
                            "w-full rounded-lg border bg-surface-low px-3 py-2 font-body text-sm text-ink focus:bg-white focus:outline-none",
                            over ? "border-red-300" : "border-transparent focus:border-primary/40",
                          )}
                        />
                        <span className={cn("block font-body text-[11px] tabular-nums", over ? "font-semibold text-red-600" : "text-ink-muted")}>
                          {field.label.trim().length}/{limit}
                          {over && " · WhatsApp cuts it here. Make it shorter."}
                        </span>
                      </div>
                      <Select
                        size="md"
                        aria-label={`Question ${index + 1} type`}
                        value={field.type}
                        disabled={!canManage}
                        className="w-44"
                        onChange={(v) => updateField(index, {
                          type: v as WaFormFieldType,
                          options: CHOICE_TYPES.includes(v as WaFormFieldType) && field.options.length === 0 ? ["", ""] : field.options,
                        })}
                        options={setup.field_types.map((t) => ({ value: t, label: FIELD_TYPE_LABELS[t] }))}
                      />
                    </div>
                    {isChoice && (
                      <div className="space-y-2 pl-7">
                        {field.options.map((option, oi) => (
                          <div key={oi} className="flex items-center gap-2">
                            <input
                              aria-label={`Question ${index + 1} option ${oi + 1}`}
                              value={option}
                              disabled={!canManage}
                              onChange={(e) => updateField(index, { options: field.options.map((o, j) => (j === oi ? e.target.value : o)) })}
                              placeholder={`Option ${oi + 1}`}
                              className={cn(
                                "min-w-0 flex-1 rounded-lg border bg-surface-low px-3 py-1.5 font-body text-sm text-ink focus:bg-white focus:outline-none",
                                option.trim().length > setup.option_limit ? "border-red-300" : "border-transparent focus:border-primary/40",
                              )}
                            />
                            <span className={cn("w-12 shrink-0 text-right font-body text-[11px] tabular-nums", option.trim().length > setup.option_limit ? "text-red-600" : "text-ink-muted")}>
                              {option.trim().length}/{setup.option_limit}
                            </span>
                            {canManage && (
                              <button
                                type="button"
                                aria-label={`Remove option ${oi + 1}`}
                                onClick={() => updateField(index, { options: field.options.filter((_, j) => j !== oi) })}
                                className="rounded-lg p-1 text-ink-muted hover:bg-red-50 hover:text-red-600"
                              >
                                <X size={14} />
                              </button>
                            )}
                          </div>
                        ))}
                        {canManage && field.options.length < (setup.max_options[field.type] ?? 20) && (
                          <button
                            type="button"
                            onClick={() => updateField(index, { options: [...field.options, ""] })}
                            className="inline-flex items-center gap-1 font-label text-xs font-semibold text-primary-600 hover:text-primary-700"
                          >
                            <Plus size={13} /> Add option
                          </button>
                        )}
                      </div>
                    )}
                    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-surface-mid pt-3 pl-7">
                      <label className="inline-flex items-center gap-2 font-label text-xs font-semibold text-ink-secondary">
                        <SwitchPill
                          size="sm"
                          on={field.required}
                          disabled={!canManage}
                          onChange={(v) => updateField(index, { required: v })}
                          aria-label={`Question ${index + 1} required`}
                        />
                        Required
                      </label>
                      {canManage && (
                        <div className="flex items-center gap-1">
                          <button type="button" aria-label="Move up" disabled={index === 0} onClick={() => moveField(index, -1)}
                            className="rounded-lg p-1.5 text-ink-muted hover:bg-surface-mid disabled:opacity-30"><ArrowUp size={14} /></button>
                          <button type="button" aria-label="Move down" disabled={index === draft.fields.length - 1} onClick={() => moveField(index, 1)}
                            className="rounded-lg p-1.5 text-ink-muted hover:bg-surface-mid disabled:opacity-30"><ArrowDown size={14} /></button>
                          <button type="button" aria-label={`Delete question ${index + 1}`}
                            onClick={() => update({ fields: draft.fields.filter((_, i) => i !== index) })}
                            className="rounded-lg p-1.5 text-ink-muted hover:bg-red-50 hover:text-red-600"><Trash2 size={14} /></button>
                        </div>
                      )}
                    </div>
                  </li>
                );
              })}
            </ol>
            {canManage && draft.fields.length < setup.max_fields && (
              <button
                type="button"
                onClick={addField}
                className="flex w-full items-center justify-center gap-1.5 rounded-2xl border border-dashed border-surface-mid py-3 font-label text-sm font-semibold text-primary-700 hover:bg-primary-light/40"
              >
                <Plus size={15} /> Add question
              </button>
            )}
          </section>
          )}

          <section aria-labelledby="when-to-send" className="space-y-3">
            <div>
              <h2 id="when-to-send" className="font-display text-base font-bold text-ink">When Anril sends it</h2>
              <p className="font-body text-xs text-ink-secondary">
                All off by default. Turn on the ones you want; turning off Auto-reply in Anril Setup → Replies &amp; handover stops these too.
              </p>
            </div>
            <WhenToSend triggers={draft.triggers} onChange={(triggers) => update({ triggers })} disabled={!canManage} />
          </section>

          <section aria-labelledby="texts" className="space-y-3">
            <div>
              <h2 id="texts" className="font-display text-base font-bold text-ink">Words on the form</h2>
              <p className="font-body text-xs text-ink-secondary">
                Filled in {setup.languages.find((l) => l.key === draft.language)?.name}. Change any of them; a changed box stays as you wrote it.
              </p>
            </div>
            <FormTextsEditor
              setup={setup}
              language={draft.language}
              texts={draft.texts}
              keys={textKeys}
              disabled={!canManage}
              onChange={(texts) => update({ texts })}
            />
          </section>

          {canManage && (
            <section className="rounded-2xl px-1">
              {confirmArchive ? (
                <div className="flex flex-wrap items-center gap-3 rounded-xl bg-red-50 px-3 py-2.5">
                  <p className="font-body text-xs text-red-800">Archive this form? It stops on WhatsApp; its answers are kept.</p>
                  <button type="button" onClick={handleArchive} className="rounded-lg bg-red-600 px-3 py-1.5 font-label text-xs font-semibold text-white hover:bg-red-700">Archive</button>
                  <button type="button" onClick={() => setConfirmArchive(false)} className="font-label text-xs font-semibold text-ink-secondary">Keep it</button>
                </div>
              ) : (
                <button type="button" onClick={() => setConfirmArchive(true)} className="inline-flex items-center gap-1.5 font-label text-xs font-semibold text-ink-muted hover:text-red-600">
                  <Trash2 size={13} /> Archive form
                </button>
              )}
            </section>
          )}
        </div>

        <aside className="lg:sticky lg:top-24 lg:self-start">
          <p className="mb-3 text-center font-label text-[11px] font-semibold uppercase tracking-wider text-ink-muted">Preview</p>
          {kind === "standard" ? (
            <FormPhonePreview fields={draft.fields} words={words} />
          ) : (
            <LiveFormPhonePreview kind={kind} settings={draft.settings} fields={draft.fields} words={words} />
          )}
        </aside>
      </div>

      {canManage && (
        <div
          className="sticky bottom-[calc(4.75rem+env(safe-area-inset-bottom,0px))] z-10 lg:bottom-0 -mx-4 mt-8 border-t border-surface-mid bg-surface-low/95 px-4 py-3 backdrop-blur supports-[backdrop-filter]:bg-surface-low/80 sm:mx-0 sm:rounded-2xl sm:border sm:px-5"
          style={{ paddingBottom: "max(0.75rem, env(safe-area-inset-bottom, 0px))" }}
        >
          <div className="flex flex-wrap items-center justify-between gap-3" aria-live="polite">
            <p className={cn(
              "min-w-0 font-body text-xs font-semibold",
              problems.length ? "text-amber-800" : dirty ? "text-amber-700" : design.status.state === "failed" ? "text-amber-800" : "text-ink-secondary",
            )}>
              {problems.length ? problems[0] : statusLine}
            </p>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleSave}
                disabled={!dirty || saving !== null || problems.length > 0}
                className="inline-flex items-center gap-1.5 rounded-xl px-4 py-2 font-label text-sm font-semibold text-ink ring-1 ring-surface-mid hover:bg-white disabled:opacity-40"
              >
                {saving === "save" && <Loader2 size={14} className="animate-spin" />} Save
              </button>
              <button
                type="button"
                onClick={handlePublish}
                disabled={saving !== null || problems.length > 0 || (!dirty && design.live)}
                className="inline-flex items-center gap-1.5 rounded-xl bg-primary px-4 py-2 font-label text-sm font-semibold text-white shadow-sm hover:bg-primary-dark disabled:opacity-40"
              >
                {saving === "publish" ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                {dirty ? "Save & publish" : "Publish"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
