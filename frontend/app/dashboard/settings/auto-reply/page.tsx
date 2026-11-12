"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { MessagesSquare, Send, Sparkles } from "lucide-react";
import { api, type AutoReplySource } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useSettingsForm } from "../SettingsFormContext";
import {
  Fact,
  Facts,
  SaveButton,
  SaveStatus,
  SectionFooter,
  SectionLoadGate,
  SettingsAccordion,
  SettingsSection,
  SummaryHint,
  SwitchPill,
  type SectionLoadState,
} from "../SettingsSection";

// Backend: services/automation_guards.py. A missing value means ON, so a source added later starts on.
const AI_KEY = "ai_auto_reply_enabled";
const TEMPLATE_KEY = "instant_templates_enabled";
const SOURCES_KEY = "auto_reply_sources";
const SECTION_ID = "automations_ai";

type Field = "ai" | "template";
type Flags = Record<string, Partial<Record<Field, boolean>>>;

const GROUP_LABELS: Record<AutoReplySource["group"], string> = {
  channel: "Chat channels",
  lead: "Lead sources",
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

export default function AutoReplySettingsPage() {
  const { settingFor, drafts, setDrafts, saveStates, canManageSettings, handleSave } = useSettingsForm();
  const [sources, setSources] = useState<AutoReplySource[]>([]);
  const [loadState, setLoadState] = useState<SectionLoadState>("loading");

  const load = useCallback(async () => {
    setLoadState("loading");
    try {
      const res = await api.settings.getAutoReplySources();
      setSources(res.sources);
      setLoadState("ready");
    } catch {
      setLoadState("error");
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const storedMaster = (key: string) => settingFor(key)?.display_value !== "false";
  const master = (key: string) => (drafts[key] !== undefined ? drafts[key] === "true" : storedMaster(key));
  const aiOn = master(AI_KEY);
  const templatesOn = master(TEMPLATE_KEY);

  const storedFlags = useMemo(() => parseFlags(settingFor(SOURCES_KEY)?.display_value), [settingFor]);
  const flags = drafts[SOURCES_KEY] !== undefined ? parseFlags(drafts[SOURCES_KEY]) : storedFlags;

  const dirty =
    aiOn !== storedMaster(AI_KEY) || templatesOn !== storedMaster(TEMPLATE_KEY) || !sameFlags(flags, storedFlags);

  const setMaster = (key: string, next: boolean) => setDrafts((d) => ({ ...d, [key]: next ? "true" : "false" }));
  const setRow = (key: string, field: Field, next: boolean) => {
    const updated = prune({ ...flags, [key]: { ...flags[key], [field]: next } });
    setDrafts((d) => ({ ...d, [SOURCES_KEY]: JSON.stringify(updated) }));
  };

  const offRows = sources.filter(
    (s) => (s.ai && !isOn(flags, s.key, "ai")) || (s.template && !isOn(flags, s.key, "template")),
  );
  const status =
    !aiOn && !templatesOn
      ? { label: "Off", tone: "off" as const }
      : aiOn && templatesOn && offRows.length === 0
        ? { label: "On", tone: "on" as const }
        : { label: "Partly on", tone: "warn" as const };

  const groups = (["channel", "lead"] as const)
    .map((g) => ({ group: g, rows: sources.filter((s) => s.group === g) }))
    .filter((g) => g.rows.length > 0);

  const cell = (source: AutoReplySource, field: Field, masterOn: boolean) =>
    source[field] ? (
      <SwitchPill
        on={isOn(flags, source.key, field)}
        size="sm"
        disabled={!canManageSettings || !masterOn}
        aria-label={`${source.label} ${field === "ai" ? "AI replies" : "instant template"}`}
        onChange={(next) => setRow(source.key, field, next)}
      />
    ) : (
      <span className="font-body text-xs text-ink-muted" aria-label="Not available">
        –
      </span>
    );

  return (
    <SettingsAccordion>
      <SettingsSection
        id="ai-auto-reply"
        icon={Sparkles}
        accent="violet"
        title="Auto-Reply"
        description="Choose what goes out automatically: AI replies in chats, and the template a new lead gets the moment they arrive. Your team's own messages are never blocked."
        status={status}
        dirty={dirty}
        summary={
          status.tone === "off" ? (
            <SummaryHint>Off. Nothing goes out automatically; messages wait for a teammate.</SummaryHint>
          ) : (
            <Facts>
              <Fact icon={MessagesSquare}>AI replies {aiOn ? "on" : "off"}</Fact>
              <Fact icon={Send}>Instant templates {templatesOn ? "on" : "off"}</Fact>
              {offRows.length > 0 && <Fact>{offRows.length} source{offRows.length === 1 ? "" : "s"} switched off</Fact>}
            </Facts>
          )
        }
      >
        <SectionLoadGate state={loadState} onRetry={load}>
          <div className="grid gap-3 sm:grid-cols-2">
            <MasterCard
              icon={MessagesSquare}
              title="AI Replies"
              on={aiOn}
              disabled={!canManageSettings}
              onChange={(next) => setMaster(AI_KEY, next)}
              offText="No AI reply anywhere: no photo/video reply, no “typing…”, no AI follow-ups or nudges. Messages wait for a teammate."
              onText="The AI replies on the channels and sources switched on below."
            />
            <MasterCard
              icon={Send}
              title="Instant Templates"
              on={templatesOn}
              disabled={!canManageSettings}
              onChange={(next) => setMaster(TEMPLATE_KEY, next)}
              offText="No welcome template to any new lead from any source. Leads are still added and assigned."
              onText="New leads get their welcome template from the sources switched on below."
            />
          </div>

          <div className="mt-4 overflow-x-auto">
            <table className="w-full border-collapse font-body text-sm">
              <thead>
                <tr className="border-b border-border-subtle">
                  <th className="py-2 pr-2 text-left font-label text-[10.5px] font-bold uppercase tracking-wider text-ink-muted">Source</th>
                  <th className="w-20 py-2 text-center font-label leading-tight sm:w-36 text-[10.5px] font-bold uppercase tracking-wider text-ink-muted">Instant template</th>
                  <th className="w-20 py-2 text-center font-label leading-tight sm:w-36 text-[10.5px] font-bold uppercase tracking-wider text-ink-muted">AI replies</th>
                </tr>
              </thead>
              {groups.map(({ group, rows }) => (
                <tbody key={group}>
                  <tr>
                    <td colSpan={3} className="bg-surface-subtle px-2 py-1.5 font-label text-[10.5px] font-bold uppercase tracking-wider text-ink-muted">
                      {GROUP_LABELS[group]}
                    </td>
                  </tr>
                  {rows.map((s) => (
                    <tr key={s.key} className="border-b border-border-subtle last:border-b-0">
                      <td className="py-2.5 pr-2">
                        <span className="font-medium text-ink">{s.label}</span>
                        {s.hint && <span className="block text-xs text-ink-muted">{s.hint}</span>}
                      </td>
                      <td className="py-2.5 text-center">
                        <div className="flex justify-center">{cell(s, "template", templatesOn)}</div>
                      </td>
                      <td className="py-2.5 text-center">
                        <div className="flex justify-center">{cell(s, "ai", aiOn)}</div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              ))}
            </table>
          </div>

          <p className="mt-3 font-body text-xs leading-relaxed text-ink-muted">
            A message goes out only when its switch above and its row are both on. AI replies for a lead source cover
            that lead&apos;s later chats, so an IndiaMART lead writing on WhatsApp needs both rows on. Always sent:
            your team&apos;s own messages, broadcasts, scheduled templates, STOP confirmations and payment messages.
          </p>

          <SectionFooter
            status={<SaveStatus state={saveStates[SECTION_ID] ?? "idle"} dirty={dirty} idleLabel={`Auto-Reply is ${status.label.toLowerCase()}`} />}
          >
            <SaveButton
              state={saveStates[SECTION_ID] ?? "idle"}
              dirty={dirty}
              disabled={!canManageSettings}
              onClick={() => handleSave(SECTION_ID, [AI_KEY, TEMPLATE_KEY, SOURCES_KEY])}
            />
          </SectionFooter>
        </SectionLoadGate>
      </SettingsSection>
    </SettingsAccordion>
  );
}

function MasterCard({
  icon: Icon,
  title,
  on,
  disabled,
  onChange,
  onText,
  offText,
}: {
  icon: typeof Sparkles;
  title: string;
  on: boolean;
  disabled: boolean;
  onChange: (next: boolean) => void;
  onText: string;
  offText: string;
}) {
  return (
    <div
      className={cn(
        "flex items-start gap-3 rounded-xl border p-3.5 transition-colors",
        on ? "border-primary/20 bg-primary/[0.03]" : "border-border bg-surface-subtle",
      )}
    >
      <Icon size={16} className={cn("mt-0.5 shrink-0", on ? "text-primary" : "text-ink-muted")} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 font-body text-sm font-semibold text-ink">
          {title}
          <span
            className={cn(
              "rounded-full px-2 py-px font-label text-[10px] font-bold tracking-wide",
              on ? "bg-emerald-50 text-emerald-700" : "bg-white text-ink-muted ring-1 ring-border",
            )}
          >
            {on ? "ON" : "OFF"}
          </span>
        </div>
        <p className="mt-0.5 font-body text-xs leading-relaxed text-ink-muted">{on ? onText : offText}</p>
      </div>
      <SwitchPill on={on} size="sm" disabled={disabled} aria-label={`${title} on or off`} onChange={onChange} />
    </div>
  );
}
