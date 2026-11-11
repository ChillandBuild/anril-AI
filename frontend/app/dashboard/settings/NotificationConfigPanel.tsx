"use client";
import { useEffect, useRef, useState } from "react";
import { Bell, Clock, FileText, MessageSquareText, Moon, Siren, Users, X } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { toast } from "sonner";
import { api, NotificationConfig, Caller, WabaTemplate } from "@/lib/api";
import {
  SaveButton,
  SaveStatus,
  SectionFooter,
  SettingsAccordion,
  SettingsSection,
  SwitchPill,
  TickMark,
  type SaveState,
} from "./SettingsSection";

const EVENT_LABELS: Record<string, string> = {
  callback_due: "Callback due reminder",
  callback_claimable: "Callback open to claim",
  callback_taken_over: "Your callback was claimed",
  lead_assigned: "New lead assigned",
  lead_replied: "Lead replied",
  handover_new: "Chat handover needed",
};

const AUDIENCE_OPTIONS: { value: NotificationConfig["claimable_audience"]; label: string }[] = [
  { value: "telecallers_and_admin", label: "Telecallers + Admin" },
  { value: "telecallers_only", label: "Telecallers only" },
  { value: "admin_only", label: "Admin only" },
  { value: "specific", label: "Specific telecallers" },
];

const SEGMENTS = ["A", "B", "C", "D"] as const;
const SEGMENT_LABELS: Record<(typeof SEGMENTS)[number], string> = { A: "Hot", B: "Warm", C: "Cold", D: "Not Interested" };
const SEGMENT_STYLES: Record<(typeof SEGMENTS)[number], string> = {
  A: "bg-segment-a-bg text-segment-a-text border-segment-a-border",
  B: "bg-segment-b-bg text-segment-b-text border-segment-b-border",
  C: "bg-segment-c-bg text-segment-c-text border-segment-c-border",
  D: "bg-segment-d-bg text-segment-d-text border-segment-d-border",
};
const E164_REGEX = /^\+[1-9]\d{6,14}$/;

/** The two WhatsApp alert blocks share this shape. */
type WhatsAppBlock = NotificationConfig["whatsapp_notifications"];

/** Which card a save came from — only that card flashes "Saved". */
type SectionKey = "push" | "lead" | "escalation";

const TOGGLE_NAMES: Record<SectionKey, string> = {
  push: "Push notifications",
  lead: "WhatsApp lead notifications",
  escalation: "WhatsApp escalation alerts",
};

const hourLabel = (h: number) => `${String(h).padStart(2, "0")}:00`;

/**
 * Owns the whole notification config but renders it as three independent
 * cards: push alerts, WhatsApp lead notifications, WhatsApp escalation
 * alerts. The API stores them in one row, so any Save writes the full
 * object — the per-card dirty flags below only decide which card lights up.
 */
export function NotificationConfigPanel({ canManage = true }: { canManage?: boolean }) {
  const [cfg, setCfg] = useState<NotificationConfig | null>(null);
  /** Last value known to be on the server — the baseline for dirty checks. */
  const [saved, setSaved] = useState<NotificationConfig | null>(null);
  const [callers, setCallers] = useState<Caller[]>([]);
  const [callersLoaded, setCallersLoaded] = useState(false);
  const [templates, setTemplates] = useState<WabaTemplate[]>([]);
  const [states, setStates] = useState<Record<SectionKey, SaveState>>({
    push: "idle",
    lead: "idle",
    escalation: "idle",
  });
  const [toggling, setToggling] = useState<Record<SectionKey, boolean>>({
    push: false,
    lead: false,
    escalation: false,
  });

  useEffect(() => {
    api.notifications
      .getConfig()
      .then((c) => {
        setCfg(c);
        setSaved(c);
      })
      .catch(() => {});
    api.callers.list().then((res) => setCallers((res.data || []).filter((c) => c.active))).catch(() => {}).finally(() => setCallersLoaded(true));
    api.templates.list().then(setTemplates).catch(() => {});
  }, []);

  function patch(next: Partial<NotificationConfig>) {
    if (!canManage) return;
    setCfg((c) => (c ? { ...c, ...next } : c));
  }

  async function save(key: SectionKey) {
    if (!cfg || !canManage) return;
    setStates((s) => ({ ...s, [key]: "saving" }));
    try {
      const next = await api.notifications.saveConfig(cfg);
      setCfg(next);
      setSaved(next);
      setStates((s) => ({ ...s, [key]: "saved" }));
      setTimeout(() => setStates((s) => ({ ...s, [key]: "idle" })), 2500);
    } catch {
      setStates((s) => ({ ...s, [key]: "idle" }));
    }
  }

  /**
   * The on/off switch in a card's header saves right away. It writes the
   * last-saved config with only that one flag changed, so half-finished edits
   * in any card stay unsaved drafts instead of riding along.
   */
  async function quickToggle(key: SectionKey, on: boolean) {
    if (!saved || !canManage) return;
    const payload: NotificationConfig =
      key === "push"
        ? { ...saved, push_enabled: on }
        : key === "lead"
        ? { ...saved, whatsapp_notifications: { ...saved.whatsapp_notifications, enabled: on } }
        : { ...saved, whatsapp_escalation_notifications: { ...saved.whatsapp_escalation_notifications, enabled: on } };
    setToggling((t) => ({ ...t, [key]: true }));
    try {
      const next = await api.notifications.saveConfig(payload);
      setSaved(next);
      setCfg((c) => {
        if (!c) return next;
        if (key === "push") return { ...c, push_enabled: next.push_enabled };
        if (key === "lead")
          return { ...c, whatsapp_notifications: { ...c.whatsapp_notifications, enabled: next.whatsapp_notifications.enabled } };
        return {
          ...c,
          whatsapp_escalation_notifications: {
            ...c.whatsapp_escalation_notifications,
            enabled: next.whatsapp_escalation_notifications.enabled,
          },
        };
      });
      toast.success(`${TOGGLE_NAMES[key]} turned ${on ? "on" : "off"}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : `Couldn't turn ${TOGGLE_NAMES[key].toLowerCase()} ${on ? "on" : "off"}`);
    } finally {
      setToggling((t) => ({ ...t, [key]: false }));
    }
  }

  if (!cfg || !saved) {
    return (
      <div className="space-y-2 sm:space-y-2.5">
        <div className="card rounded-3xl h-24 animate-pulse bg-border-subtle" />
        <div className="card rounded-3xl h-24 animate-pulse bg-border-subtle" />
        <div className="card rounded-3xl h-24 animate-pulse bg-border-subtle" />
      </div>
    );
  }

  const approvedTemplates = templates.filter((t) => t.status === "APPROVED");
  const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

  const pushDirty = !same(
    [cfg.push_enabled, cfg.events, cfg.claimable_threshold_minutes, cfg.claimable_audience, cfg.claimable_caller_ids, cfg.quiet_hours],
    [saved.push_enabled, saved.events, saved.claimable_threshold_minutes, saved.claimable_audience, saved.claimable_caller_ids, saved.quiet_hours]
  );
  const leadDirty = !same(cfg.whatsapp_notifications, saved.whatsapp_notifications);
  const escalationDirty = !same(cfg.whatsapp_escalation_notifications, saved.whatsapp_escalation_notifications);

  const eventKeys = Object.keys(EVENT_LABELS);
  const activeEvents = eventKeys.filter((k) => cfg.events[k] ?? true).length;

  const audienceLabel =
    cfg.claimable_audience === "specific"
      ? `${cfg.claimable_caller_ids.length} telecaller${cfg.claimable_caller_ids.length === 1 ? "" : "s"}`
      : AUDIENCE_OPTIONS.find((o) => o.value === cfg.claimable_audience)?.label ?? "";

  return (
    <SettingsAccordion>
      <GroupLabel>On phone and desktop</GroupLabel>
      <SettingsSection
        id="push-notifications"
        icon={Bell}
        accent="violet"
        title="Push Notifications"
        description="Phone and desktop push alerts for your team. The in-app bell always records every event regardless of these settings."
        status={
          cfg.push_enabled
            ? { label: `${activeEvents}/${eventKeys.length} events`, tone: "on" }
            : { label: "Push off", tone: "off" }
        }
        dirty={pushDirty}
        headerAction={
          <SwitchPill
            on={cfg.push_enabled}
            loading={toggling.push}
            disabled={!canManage}
            aria-label="Push notifications on or off"
            onChange={(v) => quickToggle("push", v)}
          />
        }
        summary={
          cfg.push_enabled ? (
            <Facts>
              <Fact icon={Bell}>
                {activeEvents} of {eventKeys.length} events
              </Fact>
              <Fact icon={Clock}>Callbacks open to claim after {cfg.claimable_threshold_minutes} min</Fact>
              <Fact icon={Users}>{audienceLabel}</Fact>
              {cfg.quiet_hours.enabled && (
                <Fact icon={Moon}>
                  Quiet {hourLabel(cfg.quiet_hours.start_hour)}–{hourLabel(cfg.quiet_hours.end_hour)} IST
                </Fact>
              )}
            </Facts>
          ) : (
            <SummaryHint>Off. Nobody gets phone or desktop pushes. The in-app bell still records everything.</SummaryHint>
          )
        }
      >
        <div className="space-y-4">
          {!cfg.push_enabled && (
            <p className="rounded-xl border border-border-subtle bg-surface-subtle px-3 py-2 font-body text-xs text-ink-muted">
              Push is off. Turn it on with the switch above to send these alerts.
            </p>
          )}

          {/* Per-event toggles */}
          <div className="space-y-2">
            <p className="font-label text-[11px] font-bold uppercase tracking-wider text-ink-muted">Per-event push</p>
            {eventKeys.map((key) => {
              const on = cfg.events[key] ?? true;
              return (
                <div
                  key={key}
                  className="flex items-center justify-between gap-3 rounded-xl border border-border-subtle bg-surface-subtle p-3"
                >
                  <span className="font-body text-sm text-ink">{EVENT_LABELS[key]}</span>
                  <SwitchPill
                    on={on}
                    disabled={!canManage || !cfg.push_enabled}
                    onChange={(v) => patch({ events: { ...cfg.events, [key]: v } })}
                  />
                </div>
              );
            })}
          </div>

          {/* Claimable threshold + audience */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="rounded-2xl border border-border-subtle bg-surface-subtle p-4">
              <label className="font-body text-sm font-semibold text-ink">Claimable after (minutes)</label>
              <p className="mb-2 mt-0.5 font-body text-xs text-ink-muted">How long after the slot a callback opens to claim.</p>
              <input
                type="number"
                min={1}
                max={120}
                value={cfg.claimable_threshold_minutes}
                disabled={!canManage}
                onChange={(e) =>
                  patch({ claimable_threshold_minutes: Math.max(1, Math.min(120, parseInt(e.target.value) || 1)) })
                }
                className="w-24 rounded-xl border border-border bg-white px-3 py-2 font-mono text-sm text-ink transition focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/15"
              />
            </div>
            <div className="rounded-2xl border border-border-subtle bg-surface-subtle p-4">
              <label className="font-body text-sm font-semibold text-ink">Claimable broadcast to</label>
              <p className="mb-2 mt-0.5 font-body text-xs text-ink-muted">Who gets the &quot;open to claim&quot; alert.</p>
              <select
                value={cfg.claimable_audience}
                disabled={!canManage}
                onChange={(e) => patch({ claimable_audience: e.target.value as NotificationConfig["claimable_audience"] })}
                className="w-full rounded-xl border border-border bg-white px-3 py-2 text-sm text-ink transition focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/15"
              >
                {AUDIENCE_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>

              {cfg.claimable_audience === "specific" && (
                <div className="mt-3 max-h-44 space-y-1.5 overflow-y-auto rounded-xl border border-border bg-white p-2">
                  {!callersLoaded ? (
                    <p className="px-1 py-2 font-body text-xs text-ink-muted">—</p>
                  ) : callers.length === 0 ? (
                    <p className="px-1 py-2 font-body text-xs text-ink-muted">No telecallers found.</p>
                  ) : (
                    callers.map((c) => {
                      const checked = cfg.claimable_caller_ids.includes(c.id);
                      return (
                        <button
                          key={c.id}
                          type="button"
                          role="checkbox"
                          aria-checked={checked}
                          disabled={!canManage}
                          onClick={() =>
                            patch({
                              claimable_caller_ids: checked
                                ? cfg.claimable_caller_ids.filter((id) => id !== c.id)
                                : [...cfg.claimable_caller_ids, c.id],
                            })
                          }
                          className="flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-surface-subtle disabled:cursor-not-allowed disabled:opacity-55"
                        >
                          <TickMark checked={checked} size="sm" />
                          <span className="font-body text-sm text-ink">{c.name}</span>
                        </button>
                      );
                    })
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Quiet hours */}
          <div className="rounded-2xl border border-border-subtle bg-surface-subtle p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="font-body text-sm font-semibold text-ink">Quiet hours</p>
                <p className="mt-0.5 font-body text-xs text-ink-muted">
                  Suppress pushes overnight (in-app bell still records them).
                </p>
              </div>
              <SwitchPill
                on={cfg.quiet_hours.enabled}
                disabled={!canManage}
                onChange={(v) => patch({ quiet_hours: { ...cfg.quiet_hours, enabled: v } })}
              />
            </div>
            {cfg.quiet_hours.enabled && (
              <div className="mt-3 flex items-center gap-2">
                <HourSelect
                  value={cfg.quiet_hours.start_hour}
                  disabled={!canManage}
                  onChange={(h) => patch({ quiet_hours: { ...cfg.quiet_hours, start_hour: h } })}
                />
                <span className="text-sm text-ink-muted">to</span>
                <HourSelect
                  value={cfg.quiet_hours.end_hour}
                  disabled={!canManage}
                  onChange={(h) => patch({ quiet_hours: { ...cfg.quiet_hours, end_hour: h } })}
                />
                <span className="text-xs text-ink-muted">IST</span>
              </div>
            )}
          </div>
        </div>

        <SectionFooter
          status={
            <SaveStatus
              state={states.push}
              dirty={pushDirty}
              idleLabel={cfg.push_enabled ? "Push alerts are on" : "Push alerts are off"}
            />
          }
        >
          <SaveButton state={states.push} dirty={pushDirty} disabled={!canManage} onClick={() => save("push")} />
        </SectionFooter>
      </SettingsSection>

      <GroupLabel>On WhatsApp</GroupLabel>
      <WhatsAppAlertCard
        id="whatsapp-lead-alerts"
        icon={MessageSquareText}
        accent="emerald"
        title="WhatsApp Lead Notifications"
        description="Message your team on WhatsApp when a lead's segment changes."
        switchLabel="Send a WhatsApp alert on segment change"
        switchHelp="Uses an approved WhatsApp template — the lead never sees this message."
        segmentsLabel="Notify for segments"
        delayHelp="How long the lead must stay in the segment before sending the notification. Set to 0 to send immediately."
        block={cfg.whatsapp_notifications}
        approvedTemplates={approvedTemplates}
        canManage={canManage}
        dirty={leadDirty}
        state={states.lead}
        offHint="Off. Nobody is messaged on WhatsApp when a lead's segment changes."
        delayNote=""
        toggling={toggling.lead}
        onToggle={(v) => quickToggle("lead", v)}
        onSave={() => save("lead")}
        onChange={(next) => patch({ whatsapp_notifications: next })}
      />

      <WhatsAppAlertCard
        id="whatsapp-escalation-alerts"
        icon={Siren}
        accent="amber"
        title="WhatsApp Escalation Alerts"
        description="Message your team on WhatsApp when a conversation is escalated to a human."
        switchLabel="Send a WhatsApp alert on escalation"
        switchHelp="Skipped automatically if a teammate claims or resolves the handover first."
        segmentsLabel="Alert for segments"
        delayHelp="How long to wait before alerting. If a teammate claims or resolves the handover first, the message is not sent."
        block={cfg.whatsapp_escalation_notifications}
        approvedTemplates={approvedTemplates}
        canManage={canManage}
        dirty={escalationDirty}
        state={states.escalation}
        offHint="Off. Nobody is messaged on WhatsApp when a chat needs a human."
        delayNote=", skipped if claimed"
        toggling={toggling.escalation}
        onToggle={(v) => quickToggle("escalation", v)}
        onSave={() => save("escalation")}
        onChange={(next) => patch({ whatsapp_escalation_notifications: next })}
      />
    </SettingsAccordion>
  );
}

/**
 * One WhatsApp alert configuration card: segments, recipients, template, delay.
 * The segment-change and escalation alerts differ only in copy and icon.
 */
function WhatsAppAlertCard({
  id,
  icon,
  accent,
  title,
  description,
  switchLabel,
  switchHelp,
  segmentsLabel,
  delayHelp,
  block,
  approvedTemplates,
  canManage,
  dirty,
  state,
  offHint,
  delayNote,
  toggling,
  onToggle,
  onSave,
  onChange,
}: {
  id: string;
  icon: React.ComponentProps<typeof SettingsSection>["icon"];
  accent: React.ComponentProps<typeof SettingsSection>["accent"];
  title: string;
  description: string;
  switchLabel: string;
  switchHelp: string;
  segmentsLabel: string;
  delayHelp: string;
  block: WhatsAppBlock;
  approvedTemplates: WabaTemplate[];
  canManage: boolean;
  dirty: boolean;
  state: SaveState;
  /** Collapsed-card line shown while the alert is off. */
  offHint: string;
  /** Appended to the delay fact, e.g. ", skipped if claimed". */
  delayNote: string;
  toggling: boolean;
  onToggle: (on: boolean) => void;
  onSave: () => void;
  onChange: (next: WhatsAppBlock) => void;
}) {
  const selectedTemplate = approvedTemplates.find((t) => t.id === block.template_id) || null;
  const incomplete = block.enabled && (!block.template_id || block.recipient_phones.length === 0);
  const delay = block.delay_minutes ?? 5;
  const phones = block.recipient_phones;

  const summary = !block.enabled ? (
    <SummaryHint>{offHint}</SummaryHint>
  ) : incomplete ? (
    <SummaryHint tone="warn">Needs a message template and at least one number. Nothing is sent until both are set.</SummaryHint>
  ) : block.target_segments.length === 0 ? (
    <SummaryHint tone="warn">No segments picked, so nothing is sent. Open this card to pick at least one.</SummaryHint>
  ) : (
    <Facts>
      {SEGMENTS.filter((s) => block.target_segments.includes(s)).map((s) => (
        <span
          key={s}
          className={`inline-flex items-center rounded-full border px-2 py-0.5 font-mono text-[11px] font-semibold ${SEGMENT_STYLES[s]}`}
        >
          {s} · {SEGMENT_LABELS[s]}
        </span>
      ))}
      <Fact icon={Users} mono={phones.length === 1}>
        {phones.length === 1 ? phones[0] : `${phones.length} numbers`}
      </Fact>
      <Fact icon={Clock}>
        {delay === 0 ? "Sends right away" : `After ${delay} min`}
        {delayNote}
      </Fact>
      {selectedTemplate && (
        <Fact icon={FileText} mono>
          {selectedTemplate.name}
        </Fact>
      )}
    </Facts>
  );

  function toggleSegment(segment: (typeof SEGMENTS)[number]) {
    const active = block.target_segments.includes(segment);
    onChange({
      ...block,
      target_segments: active
        ? block.target_segments.filter((s) => s !== segment)
        : [...block.target_segments, segment],
    });
  }

  return (
    <SettingsSection
      id={id}
      icon={icon}
      accent={accent}
      title={title}
      description={description}
      status={
        !block.enabled
          ? { label: "Off", tone: "off" }
          : incomplete
          ? { label: "Needs setup", tone: "warn" }
          : {
              label: `${block.recipient_phones.length} recipient${block.recipient_phones.length === 1 ? "" : "s"}`,
              tone: "on",
            }
      }
      dirty={dirty}
      headerAction={
        <SwitchPill
          on={block.enabled}
          loading={toggling}
          disabled={!canManage}
          aria-label={switchLabel}
          onChange={onToggle}
        />
      }
      summary={summary}
    >
      <div className="space-y-4">
        <p className="rounded-xl border border-border-subtle bg-surface-subtle px-3 py-2 font-body text-xs text-ink-muted">
          {block.enabled
            ? switchHelp
            : "This alert is off. Turn it on with the switch above to pick segments, numbers and a template."}
        </p>

        {block.enabled && (
          <div className="space-y-4">
            {incomplete && (
              <p className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 font-body text-xs text-amber-700">
                Pick a message template and add at least one recipient — nothing is sent until both are set.
              </p>
            )}

            <div>
              <p className="mb-2 font-label text-[11px] font-bold uppercase tracking-wider text-ink-muted">{segmentsLabel}</p>
              <div className="flex flex-wrap gap-2">
                {SEGMENTS.map((s) => {
                  const active = block.target_segments.includes(s);
                  return (
                    <button
                      key={s}
                      type="button"
                      aria-pressed={active}
                      disabled={!canManage}
                      onClick={() => toggleSegment(s)}
                      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 font-mono text-xs font-semibold transition-colors ${
                        active ? SEGMENT_STYLES[s] : "border-border bg-white text-ink-muted hover:border-primary/30"
                      }`}
                    >
                      {s} · {SEGMENT_LABELS[s]}
                    </button>
                  );
                })}
              </div>
            </div>

            <PhoneRecipients
              phones={block.recipient_phones}
              disabled={!canManage}
              onChange={(next) => onChange({ ...block, recipient_phones: next })}
            />

            <div>
              <label className="mb-2 block font-label text-[11px] font-bold uppercase tracking-wider text-ink-muted">
                Message template
              </label>
              <select
                value={block.template_id ?? ""}
                disabled={!canManage}
                onChange={(e) => onChange({ ...block, template_id: e.target.value || null })}
                className="w-full rounded-xl border border-border bg-white px-3 py-2 text-sm text-ink transition focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/15"
              >
                <option value="">Select a template…</option>
                {approvedTemplates.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
              {selectedTemplate && (
                <div className="mt-2 rounded-xl border border-border-subtle bg-white p-3">
                  <p className="mb-1 font-label text-[10px] font-bold uppercase tracking-wider text-ink-muted">Preview</p>
                  <p className="whitespace-pre-wrap font-mono text-xs text-ink-muted">
                    {selectedTemplate.body_text || "No body text available."}
                  </p>
                </div>
              )}
            </div>

            <div>
              <label className="mb-2 block font-label text-[11px] font-bold uppercase tracking-wider text-ink-muted">
                Delay before sending (minutes)
              </label>
              <input
                type="number"
                min={0}
                max={1440}
                value={block.delay_minutes ?? 5}
                disabled={!canManage}
                onChange={(e) =>
                  onChange({ ...block, delay_minutes: Math.max(0, Math.min(1440, parseInt(e.target.value) || 0)) })
                }
                className="w-24 rounded-xl border border-border bg-white px-3 py-2 font-mono text-sm text-ink transition focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/15"
              />
              <p className="mt-1 font-body text-[11px] text-ink-muted">{delayHelp}</p>
            </div>
          </div>
        )}
      </div>

      <SectionFooter
        status={<SaveStatus state={state} dirty={dirty} idleLabel={block.enabled ? "Alerts are on" : "Alerts are off"} />}
      >
        <SaveButton state={state} dirty={dirty} disabled={!canManage} onClick={onSave} />
      </SectionFooter>
    </SettingsSection>
  );
}

/**
 * Recipient numbers as a tag field.
 *
 * The old version was a plain text box beside an "Add Number" button, and
 * people typed a number, hit Save, and lost it — the number never left the
 * box. Here a number becomes a chip the moment you press Enter, type a
 * comma, or simply click away, so there is no step left to forget. Pasting
 * a list of numbers splits them all at once.
 */
function PhoneRecipients({
  phones,
  onChange,
  disabled = false,
}: {
  phones: string[];
  onChange: (next: string[]) => void;
  disabled?: boolean;
}) {
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [focused, setFocused] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  /** Commits everything in the box. Returns false if something was rejected. */
  function commit(raw: string): boolean {
    const candidates = raw
      .split(/[,;\n\r]+/)
      .map((c) => c.trim())
      .filter(Boolean);
    if (candidates.length === 0) {
      setText("");
      setError(null);
      return true;
    }

    const accepted: string[] = [];
    for (const candidate of candidates) {
      const normalised = candidate.replace(/[\s()\-.]/g, "");
      if (!E164_REGEX.test(normalised)) {
        setError(`"${candidate}" isn't a valid number. Include the country code, like +919876543210.`);
        setText(candidate);
        return false;
      }
      if (phones.includes(normalised) || accepted.includes(normalised)) {
        setError(`${normalised} is already on the list.`);
        setText(candidate);
        return false;
      }
      accepted.push(normalised);
    }

    onChange([...phones, ...accepted]);
    setText("");
    setError(null);
    return true;
  }

  function remove(phone: string) {
    onChange(phones.filter((p) => p !== phone));
    setError(null);
  }

  return (
    <div>
      <p className="mb-2 font-label text-[11px] font-bold uppercase tracking-wider text-ink-muted">
        Recipient phone numbers
      </p>

      {/* One field: chips and the cursor live in the same box */}
      <div
        onClick={() => inputRef.current?.focus()}
        className={`flex flex-wrap items-center gap-1.5 rounded-xl border bg-white p-2 transition ${
          disabled ? "cursor-not-allowed opacity-60" : "cursor-text"
        } ${
          error
            ? "border-red-400 ring-2 ring-red-100"
            : focused
            ? "border-primary ring-2 ring-primary/15"
            : "border-border"
        }`}
      >
        {phones.map((phone) => (
          <span
            key={phone}
            className="inline-flex items-center gap-1.5 rounded-lg border border-primary-muted bg-primary-light py-1 pl-2.5 pr-1.5 font-mono text-[13px] font-semibold text-primary"
          >
            {phone}
            <button
              type="button"
              disabled={disabled}
              onClick={(e) => {
                e.stopPropagation();
                remove(phone);
              }}
              aria-label={`Remove ${phone}`}
              className="grid h-4 w-4 place-items-center rounded-full text-primary/60 transition-colors hover:bg-primary/15 hover:text-primary disabled:cursor-not-allowed"
            >
              <X size={11} strokeWidth={3} />
            </button>
          </span>
        ))}

        <input
          ref={inputRef}
          type="tel"
          inputMode="tel"
          value={text}
          disabled={disabled}
          onFocus={() => setFocused(true)}
          onBlur={() => {
            setFocused(false);
            commit(text);
          }}
          onChange={(e) => {
            setText(e.target.value);
            if (error) setError(null);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault();
              commit(text);
            } else if (e.key === "Backspace" && text === "" && phones.length > 0) {
              remove(phones[phones.length - 1]);
            }
          }}
          placeholder={phones.length === 0 ? "+919876543210" : "Add another…"}
          className="min-w-[150px] flex-1 bg-transparent px-1.5 py-1 font-mono text-sm text-ink placeholder:font-body placeholder:text-ink-muted focus:outline-none disabled:cursor-not-allowed"
        />
      </div>

      {error ? (
        <p className="mt-1.5 font-body text-xs text-red-600">{error}</p>
      ) : (
        <p className="mt-1.5 font-body text-[11px] text-ink-muted">
          {phones.length === 0
            ? "Type a number and press Enter. Include the country code."
            : `${phones.length} number${phones.length === 1 ? "" : "s"} will be alerted. Press Enter after each one — or just click away.`}
        </p>
      )}
    </div>
  );
}

/** Divider label that groups cards by where the alert arrives. */
function GroupLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3 px-1 pb-0.5 pt-3 first:pt-0">
      <span className="font-label text-[11px] font-bold uppercase tracking-wider text-ink-muted">{children}</span>
      <span aria-hidden className="h-px flex-1 bg-border-subtle" />
    </div>
  );
}

/* The collapsed-card summary renders inside the header <button>, so these
   are spans only (no block elements, nothing interactive). */

function Facts({ children }: { children: React.ReactNode }) {
  return <span className="flex flex-wrap items-center gap-1.5">{children}</span>;
}

function Fact({ icon: Icon, mono = false, children }: { icon: LucideIcon; mono?: boolean; children: React.ReactNode }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-lg border border-border-subtle bg-surface-subtle px-2 py-0.5 text-xs text-ink-secondary ${
        mono ? "font-mono font-medium" : "font-body font-semibold"
      }`}
    >
      <Icon size={12} className="shrink-0 text-ink-muted" />
      {children}
    </span>
  );
}

function SummaryHint({ tone = "muted", children }: { tone?: "muted" | "warn"; children: React.ReactNode }) {
  return (
    <span className={`block font-body text-xs ${tone === "warn" ? "font-semibold text-amber-700" : "text-ink-muted"}`}>
      {children}
    </span>
  );
}

function HourSelect({ value, onChange, disabled }: { value: number; onChange: (h: number) => void; disabled?: boolean }) {
  return (
    <select
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(parseInt(e.target.value))}
      className="rounded-xl border border-border bg-white px-3 py-2 font-mono text-sm text-ink transition focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/15"
    >
      {Array.from({ length: 24 }, (_, h) => (
        <option key={h} value={h}>
          {String(h).padStart(2, "0")}:00
        </option>
      ))}
    </select>
  );
}
