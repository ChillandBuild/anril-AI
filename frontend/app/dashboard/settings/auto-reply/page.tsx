"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { ArrowRight, MessageCircle } from "lucide-react";
import { toast } from "sonner";
import { api, type AutoReplySource } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useSettingsForm } from "../SettingsFormContext";
import { HandoverFields, useInboxConfig } from "../InboxConfigPanel";
import { AfterHoursFields, useAfterHours } from "../AfterHoursPanel";
import { SaveButton, SaveStatus, SectionLoadGate, SwitchPill, type SaveState, type SectionLoadState } from "../SettingsSection";

// Backend: services/automation_guards.py. A missing value means ON, so a source added later starts on.
const AI_KEY = "ai_auto_reply_enabled";
const TEMPLATE_KEY = "instant_templates_enabled";
const SOURCES_KEY = "auto_reply_sources";
const SECTION_ID = "automations_ai";

type Field = "ai" | "template";
type Flags = Record<string, Partial<Record<Field, boolean>>>;

/** Where each lead source's welcome template is picked today. */
const TEMPLATE_HOME: Record<string, { href: string; where: string }> = {
  instant_forms: { href: "/dashboard/meta-ads/instant-forms", where: "each form" },
  indiamart: { href: "/dashboard/settings/connect-channels", where: "IndiaMART tile" },
  justdial: { href: "/dashboard/settings/connect-channels", where: "JustDial tile" },
  website: { href: "/dashboard/auto-messages", where: "Website form" },
  partner: { href: "/dashboard/developer", where: "Developer" },
};

function parseFlags(raw: string | undefined): Flags {
  if (!raw || raw === "Not set") return {};
  try {
    const data = JSON.parse(raw);
    return data && typeof data === "object" && !Array.isArray(data) ? (data as Flags) : {};
  } catch {
    return {};
  }
}

/** Only the switches that are off are kept: missing = on. */
function prune(flags: Flags): Flags {
  const out: Flags = {};
  for (const [key, row] of Object.entries(flags)) {
    const off = Object.fromEntries(Object.entries(row).filter(([, v]) => v === false));
    if (Object.keys(off).length) out[key] = off;
  }
  return out;
}

function sameFlags(a: Flags, b: Flags): boolean {
  const norm = (f: Flags) =>
    JSON.stringify(Object.entries(prune(f)).map(([k, v]) => [k, Object.keys(v).sort()]).sort());
  return norm(a) === norm(b);
}

function isOn(flags: Flags, key: string, field: Field): boolean {
  return flags[key]?.[field] !== false;
}

export default function RepliesAndHandoverPage() {
  const { settingFor, drafts, setDrafts, canManageSettings, handleSave } = useSettingsForm();
  const inbox = useInboxConfig();
  const afterHours = useAfterHours();
  const [sources, setSources] = useState<AutoReplySource[]>([]);
  const [sourcesState, setSourcesState] = useState<SectionLoadState>("loading");
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [errors, setErrors] = useState<string[]>([]);

  const loadSources = useCallback(async () => {
    setSourcesState("loading");
    try {
      const res = await api.settings.getAutoReplySources();
      setSources(res.sources);
      setSourcesState("ready");
    } catch {
      setSourcesState("error");
    }
  }, []);
  useEffect(() => void loadSources(), [loadSources]);

  // What was just saved, shown until the save's reload finishes. handleSave clears the drafts
  // before it reloads the settings, so without this the switches flash back to the old values.
  const [saving, setSaving] = useState<{ ai: boolean; templates: boolean; flags: Flags } | null>(null);

  const storedMaster = (key: string) => settingFor(key)?.display_value !== "false";
  // An empty draft is the form's copy of a never-set value: treat it as not edited (default on).
  const master = (key: string) => (drafts[key] ? drafts[key] === "true" : storedMaster(key));
  const aiOn = saving?.ai ?? master(AI_KEY);
  const templatesOn = saving?.templates ?? master(TEMPLATE_KEY);

  const storedFlags = useMemo(() => parseFlags(settingFor(SOURCES_KEY)?.display_value), [settingFor]);
  const flags = saving?.flags ?? (drafts[SOURCES_KEY] ? parseFlags(drafts[SOURCES_KEY]) : storedFlags);

  const repliesDirty =
    aiOn !== storedMaster(AI_KEY) || templatesOn !== storedMaster(TEMPLATE_KEY) || !sameFlags(flags, storedFlags);
  const dirty = repliesDirty || inbox.dirty || afterHours.dirty;
  const busy = saveState === "saving";
  const locked = !canManageSettings || busy;

  const setMaster = (key: string, next: boolean) => setDrafts((d) => ({ ...d, [key]: next ? "true" : "false" }));
  const setRow = (key: string, field: Field, next: boolean) => {
    const updated = prune({ ...flags, [key]: { ...flags[key], [field]: next } });
    setDrafts((d) => ({ ...d, [SOURCES_KEY]: JSON.stringify(updated) }));
  };

  /** One Save: the three settings groups save together; any that fail are named. */
  const saveAll = async () => {
    if (!canManageSettings || !dirty) return;
    setSaveState("saving");
    setErrors([]);
    if (repliesDirty) setSaving({ ai: aiOn, templates: templatesOn, flags });
    const jobs: Promise<string | null>[] = [];
    if (repliesDirty) {
      jobs.push(
        handleSave(SECTION_ID, [AI_KEY, TEMPLATE_KEY, SOURCES_KEY])
          .then((ok) => (ok ? null : "Welcome templates and AI replies did not save"))
          .finally(() => setSaving(null)),
      );
    }
    if (inbox.dirty) jobs.push(inbox.save());
    if (afterHours.dirty) jobs.push(afterHours.save());
    const failed = (await Promise.all(jobs)).filter((e): e is string => !!e);
    if (failed.length) {
      setErrors(failed);
      setSaveState("idle");
      toast.error(failed.length === jobs.length ? "Nothing saved. Please try again." : "Some changes did not save");
      return;
    }
    setSaveState("saved");
    toast.success("Replies & handover saved");
    setTimeout(() => setSaveState("idle"), 2000);
  };

  const templateRows = sources.filter((s) => s.template);
  const aiGroups = (["channel", "lead"] as const)
    .map((g) => ({ group: g, rows: sources.filter((s) => s.group === g && s.ai) }))
    .filter((g) => g.rows.length > 0);

  const sourceSwitch = (s: AutoReplySource, field: Field, masterOn: boolean) => (
    <SwitchPill
      on={isOn(flags, s.key, field)}
      size="sm"
      disabled={locked || !masterOn}
      aria-label={`${s.label} ${field === "ai" ? "AI replies" : "welcome template"}`}
      onChange={(next) => setRow(s.key, field, next)}
    />
  );

  return (
    <div className="space-y-4 pb-24">
      <div className="card flex flex-wrap items-center gap-5 rounded-2xl p-5">
        <Image src="/login/tealy-poster.png" alt="Tealy" width={150} height={150} className="hidden h-[150px] w-[150px] shrink-0 object-contain sm:block" />
        <div className="min-w-0 flex-1">
          <h2 className="font-headline text-lg font-bold text-ink">How Anril handles a new chat, start to finish</h2>
          <p className="mt-1 max-w-prose font-body text-sm text-ink-muted">
            Each step has its own switch. Turn a step off and the chat goes straight to the next one. Messages your team sends,
            broadcasts, opt-out confirmations and payment notices always go out.
          </p>
        </div>
        <Link
          href="/dashboard/brain?section=test"
          className="inline-flex items-center gap-2 rounded-xl border border-border bg-white px-4 py-2 font-label text-sm font-semibold text-ink hover:border-primary/40"
        >
          <MessageCircle size={15} className="text-primary" /> Try it in Test chat
        </Link>
      </div>

      <div className="flex flex-wrap items-stretch gap-3 xl:flex-nowrap">
        <Step n={1} title="New lead arrives" subtitle="Send your welcome template at once" on={templatesOn} onToggle={(v) => setMaster(TEMPLATE_KEY, v)} disabled={locked}>
          <SectionLoadGate state={sourcesState} onRetry={loadSources}>
            <ul className="space-y-2">
              {templateRows.map((s) => {
                const home = TEMPLATE_HOME[s.key];
                return (
                  <SourceRow key={s.key} label={s.label} control={sourceSwitch(s, "template", templatesOn)}>
                    {home && (
                      <Link href={home.href} className="font-body text-xs font-semibold text-primary hover:underline">
                        Template: set in {home.where} · change
                      </Link>
                    )}
                  </SourceRow>
                );
              })}
            </ul>
          </SectionLoadGate>
        </Step>
        <StepArrow />
        <Step n={2} title="AI replies" subtitle="Anril answers on these sources" on={aiOn} onToggle={(v) => setMaster(AI_KEY, v)} disabled={locked}>
          <SectionLoadGate state={sourcesState} onRetry={loadSources}>
            <div className="space-y-3">
              {aiGroups.map(({ group, rows }) => (
                <div key={group}>
                  <div className="mb-1.5 font-label text-xs font-semibold uppercase tracking-wider text-ink-muted">
                    {group === "channel" ? "Chat channels" : "Lead sources"}
                  </div>
                  <ul className="space-y-2">
                    {rows.map((s) => (
                      <SourceRow key={s.key} label={s.label} control={sourceSwitch(s, "ai", aiOn)} />
                    ))}
                  </ul>
                </div>
              ))}
              <p className="font-body text-xs leading-relaxed text-ink-muted">
                A lead from a source keeps that source&apos;s setting in later chats: an IndiaMART lead writing on WhatsApp needs both on.
              </p>
            </div>
          </SectionLoadGate>
        </Step>
        <StepArrow />
        <Step
          n={3}
          title="Hand to your team"
          subtitle="When the AI should stop and pass the chat on"
          on={inbox.draft.enabled}
          onToggle={(v) => inbox.setDraft({ ...inbox.draft, enabled: v })}
          disabled={locked || inbox.loadState !== "ready"}
        >
          <SectionLoadGate state={inbox.loadState} onRetry={inbox.load}>
            <HandoverFields state={inbox} disabled={locked} />
          </SectionLoadGate>
        </Step>
        <StepArrow />
        <Step
          n={4}
          title="When you're closed"
          subtitle="What Anril says while the team is out"
          on={afterHours.draft.enabled}
          onToggle={(v) => afterHours.setDraft({ ...afterHours.draft, enabled: v })}
          disabled={locked || afterHours.loadState !== "ready"}
        >
          <SectionLoadGate state={afterHours.loadState} onRetry={afterHours.load}>
            <AfterHoursFields state={afterHours} disabled={locked} />
          </SectionLoadGate>
        </Step>
      </div>

      <div className="sticky bottom-[calc(var(--mobile-nav-h)+env(safe-area-inset-bottom,0px)+0.5rem)] lg:bottom-3 z-10 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border-subtle bg-white/95 px-4 py-3 shadow-lg backdrop-blur">
        <div className="min-w-0">
          {errors.length > 0 ? (
            <ul role="alert" className="font-body text-sm text-danger">
              {errors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          ) : (
            <SaveStatus state={saveState} dirty={dirty} idleLabel="All four steps are saved" />
          )}
        </div>
        <SaveButton state={saveState} dirty={dirty} disabled={!canManageSettings} onClick={saveAll} />
      </div>
    </div>
  );
}

function Step({
  n,
  title,
  subtitle,
  on,
  onToggle,
  disabled,
  children,
}: {
  n: number;
  title: string;
  subtitle: string;
  on: boolean;
  onToggle: (next: boolean) => void;
  disabled: boolean;
  children: React.ReactNode;
}) {
  return (
    <section className={cn("card flex min-w-0 flex-[1_1_260px] flex-col gap-3 rounded-2xl p-4", !on && "bg-surface-subtle")}>
      <div className="flex items-start gap-3">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary font-label text-sm font-bold text-white">{n}</span>
        <div className="min-w-0 flex-1">
          <h2 className="font-headline text-base font-bold text-ink">{title}</h2>
          <p className="font-body text-xs text-ink-muted">{subtitle}</p>
        </div>
        <SwitchPill on={on} size="sm" disabled={disabled} aria-label={`${title} on or off`} onChange={onToggle} />
      </div>
      {!on && <p className="font-body text-xs text-ink-muted">Off. Chats skip this step. You can still change it and turn it on later.</p>}
      <div>{children}</div>
    </section>
  );
}

function SourceRow({ label, control, children }: { label: string; control: React.ReactNode; children?: React.ReactNode }) {
  return (
    <li className="flex items-center gap-3 rounded-xl border border-border-subtle px-3 py-2">
      <div className="min-w-0 flex-1">
        <div className="font-body text-sm font-medium text-ink">{label}</div>
        {children}
      </div>
      {control}
    </li>
  );
}

function StepArrow() {
  return (
    <div aria-hidden className="hidden shrink-0 items-center text-ink-muted xl:flex">
      <ArrowRight size={18} />
    </div>
  );
}
