"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { api, ReengagementLog, ReengagementStep, WabaTemplate } from "@/lib/api";
import { Select } from "@/components/ui/Select";
import {
  DelayUnit,
  MAX_DELAY_DAYS,
  MAX_DELAY_HOURS,
  formatDelay,
  isDayStep,
  splitDelay,
  toDelayHours,
} from "./reengagementDelay";

const STATUS_LABELS: Record<string, { label: string; cls: string }> = {
  sent: { label: "Sent", cls: "bg-emerald-100 text-emerald-700" },
  sent_fallback: { label: "Sent (template)", cls: "bg-primary-light text-primary" },
  skipped_window: { label: "Skipped", cls: "bg-amber-100 text-amber-700" },
  failed: { label: "Failed", cls: "bg-red-100 text-red-700" },
};

function StepLogPanel({ stepId }: { stepId: string }) {
  const [logs, setLogs] = useState<ReengagementLog[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.reengagement.getLogs(stepId).then(setLogs).catch(() => {}).finally(() => setLoading(false));
  }, [stepId]);

  const counts = logs.reduce<Record<string, number>>((acc, l) => {
    acc[l.status] = (acc[l.status] || 0) + 1;
    return acc;
  }, {});

  if (loading) return <p className="mt-3 text-xs text-on-surface-muted">Loading history…</p>;
  if (!logs.length) return <p className="mt-3 text-xs text-on-surface-muted">No sends yet for this step.</p>;

  return (
    <div className="mt-3 space-y-2">
      <div className="flex flex-wrap gap-2">
        {Object.entries(counts).map(([status, n]) => {
          const s = STATUS_LABELS[status] || { label: status, cls: "bg-on-surface/10 text-on-surface" };
          return (
            <span key={status} className={`rounded-full px-2 py-0.5 text-xs font-medium ${s.cls}`}>
              {s.label}: {n}
            </span>
          );
        })}
      </div>
      <div className="max-h-48 overflow-y-auto rounded-xl border border-on-surface/10">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-on-surface/10 bg-surface/60 text-on-surface-muted">
              <th className="px-3 py-2 text-left">Lead</th>
              <th className="px-3 py-2 text-left">Phone</th>
              <th className="px-3 py-2 text-left">Status</th>
              <th className="px-3 py-2 text-left">Time</th>
            </tr>
          </thead>
          <tbody>
            {logs.map((l) => {
              const s = STATUS_LABELS[l.status] || { label: l.status, cls: "bg-on-surface/10 text-on-surface" };
              return (
                <tr key={l.id} className="border-b border-on-surface/5 last:border-0">
                  <td className="px-3 py-1.5">{l.leads?.name || "—"}</td>
                  <td className="px-3 py-1.5 font-mono">{l.leads?.phone || l.lead_id.slice(0, 8)}</td>
                  <td className="px-3 py-1.5">
                    <span className={`rounded-full px-2 py-0.5 ${s.cls}`}>{s.label}</span>
                    {l.reason && <span className="mt-1 block text-ink-muted">{l.reason}</span>}
                  </td>
                  <td className="px-3 py-1.5 text-on-surface-muted">
                    {new Date(l.sent_at).toLocaleString()}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const SEGMENTS = ["A", "B", "C", "D"] as const;
const SEGMENT_LABELS: Record<string, string> = { A: "Hot", B: "Warm", C: "Cold", D: "Not Interested" };
const SOURCES = ["organic", "meta_ads", "csv", "telegram", "instagram", "facebook"] as const;
const SOURCE_LABELS: Record<string, string> = {
  organic: "Organic WhatsApp",
  meta_ads: "Meta Ads",
  csv: "CSV Import",
  telegram: "Telegram",
  instagram: "Instagram",
  facebook: "Facebook",
};
const DAY_STEP_NOTE =
  "After 24 hours WhatsApp only allows an approved template (Meta charges for it). Sends 10 AM–8 PM, Mon–Sat, at most 1 a day per person.";

function placeholderCount(body?: string | null): number {
  if (!body) return 0;
  const matches = body.match(/\{\{[^}]+\}\}/g);
  return matches ? new Set(matches).size : 0;
}

interface ReengagementBuilderProps {
  type: "broadcast" | "inbound";
  broadcastId?: string;
  templates: WabaTemplate[];
  canManage?: boolean;
}

export default function ReengagementBuilder({ type, broadcastId, templates, canManage = false }: ReengagementBuilderProps) {
  const [steps, setSteps] = useState<ReengagementStep[]>([]);
  // Starts true: the first fetch runs on mount, so "No messages yet" mustn't flash first.
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [expandedLog, setExpandedLog] = useState<string | null>(null);

  const [delayValue, setDelayValue] = useState(6);
  const [delayUnit, setDelayUnit] = useState<DelayUnit>("hours");
  const [segments, setSegments] = useState<string[]>(["C"]);
  const [sources, setSources] = useState<string[]>([]);
  const [messageType, setMessageType] = useState<"freeform" | "template">("freeform");
  const [content, setContent] = useState("");
  const [templateName, setTemplateName] = useState("");
  const [fallbackTemplate, setFallbackTemplate] = useState("");

  // What is stored (hours), or null while the typed number is not a whole number from 1 to 30 days.
  const delayHours = toDelayHours(delayValue, delayUnit);
  const dayStep = delayHours !== null && isDayStep(delayHours);

  /** From 24 hours on only an approved template may go out, so free text is switched off. */
  function changeDelay(value: number, unit: DelayUnit) {
    setDelayValue(value);
    setDelayUnit(unit);
    const hours = toDelayHours(value, unit);
    if (hours !== null && isDayStep(hours)) setMessageType("template");
  }

  const varCountByName = useMemo(() => {
    const m: Record<string, number> = {};
    for (const t of templates) m[t.name] = placeholderCount(t.body_text);
    return m;
  }, [templates]);

  function varsFor(name: string): string[] {
    return (varCountByName[name] ?? 0) === 0 ? [] : ["name"];
  }

  const fetchSteps = useCallback(async () => {
    if (type === "broadcast" && !broadcastId) {
      setSteps([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const rows = await api.reengagement.listSteps(
        type === "broadcast" ? { type: "broadcast", broadcast_id: broadcastId } : { type: "inbound" }
      );
      setSteps([...rows].sort((a, b) => a.delay_hours - b.delay_hours));
    } catch {
      toast.error("Failed to load sequence");
    } finally {
      setLoading(false);
    }
  }, [type, broadcastId]);

  useEffect(() => {
    fetchSteps();
  }, [fetchSteps]);

  function toggleSegment(s: string) {
    setSegments((prev) => (prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s]));
  }

  function toggleSource(s: string) {
    setSources((prev) => (prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s]));
  }

  function resetForm() {
    setDelayValue(6);
    setDelayUnit("hours");
    setSegments(["C"]);
    setSources([]);
    setMessageType("freeform");
    setContent("");
    setTemplateName("");
    setFallbackTemplate("");
  }

  function startEdit(step: ReengagementStep) {
    if (!canManage) return;
    setEditingId(step.id);
    const d = splitDelay(step.delay_hours);
    setDelayValue(d.value);
    setDelayUnit(d.unit);
    setSegments(step.target_segments);
    setSources(step.target_sources ?? []);
    setMessageType(step.message_type);
    setContent(step.message_content ?? "");
    setTemplateName(step.template_name ?? "");
    setFallbackTemplate(step.fallback_template_name ?? "");
    setShowAdd(true);
  }

  function cancelForm() {
    setShowAdd(false);
    setEditingId(null);
    resetForm();
  }

  async function saveStep() {
    if (!canManage) return;
    if (delayHours === null) {
      toast.error(`Wait must be a whole number, from 1 hour up to ${MAX_DELAY_DAYS} days`);
      return;
    }
    if (isDayStep(delayHours) && messageType !== "template") {
      toast.error("After 24 hours WhatsApp only allows an approved template. Pick one.");
      return;
    }
    if (segments.length === 0) {
      toast.error("Select at least one target segment");
      return;
    }
    if (messageType === "freeform" && !content.trim()) {
      toast.error("Message content is required");
      return;
    }
    if (messageType === "template" && !templateName) {
      toast.error(isDayStep(delayHours) ? "After 24 hours WhatsApp only allows an approved template. Pick one." : "Select a template");
      return;
    }
    if (messageType === "template" && (varCountByName[templateName] ?? 0) >= 2) {
      toast.error("Multi-variable templates aren't supported as re-engagement messages yet");
      return;
    }
    if (messageType === "freeform" && fallbackTemplate && (varCountByName[fallbackTemplate] ?? 0) >= 2) {
      toast.error("Multi-variable backup templates aren't supported yet");
      return;
    }
    const payload = {
      delay_hours: delayHours,
      target_segments: segments,
      target_sources: sources.length ? sources : null,
      message_type: messageType,
      message_content: messageType === "freeform" ? content : null,
      template_name: messageType === "template" ? templateName : null,
      template_variables: messageType === "template" ? varsFor(templateName) : null,
      fallback_template_name: messageType === "freeform" && fallbackTemplate ? fallbackTemplate : null,
      fallback_template_variables: messageType === "freeform" && fallbackTemplate ? varsFor(fallbackTemplate) : null,
    };
    try {
      if (editingId) {
        await api.reengagement.updateStep(editingId, payload);
        toast.success("Message updated");
      } else {
        await api.reengagement.createStep({
          type,
          broadcast_id: type === "broadcast" ? broadcastId : null,
          ...payload,
        });
        toast.success("Message added to sequence");
      }
      cancelForm();
      fetchSteps();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save message");
    }
  }

  async function removeStep(id: string) {
    if (!canManage) return;
    if (!confirm("Remove this message from the sequence?")) return;
    try {
      await api.reengagement.deleteStep(id);
      toast.success("Message removed");
      fetchSteps();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to remove message");
    }
  }

  // The bar covers the 24-hour window, or stretches to the longest day-step.
  const timelineMax = Math.max(24, ...steps.map((s) => s.delay_hours));
  const anchorLabel = type === "broadcast" ? "after the broadcast was sent" : "after the lead replied";

  return (
    <div className="space-y-6">
      {/* Clock explainer */}
      <div className="rounded-2xl border border-on-surface/10 bg-surface/50 p-5">
        <h3 className="font-label text-xs uppercase tracking-widest text-on-surface-muted">
          {type === "broadcast" ? "Campaign Follow-up" : "Lead Reply Follow-up"} — how timing works
        </h3>
        <p className="mt-2 text-sm text-on-surface">
          {type === "broadcast" ? (
            <>Each message fires a set number of hours <strong>after the broadcast is sent</strong>. Per lead, when a
            message fires: if their 24h WhatsApp window is still open it sends as <strong>freeform</strong>; otherwise
            your <strong>backup template</strong> is sent instead (or the lead is skipped if no backup is set).</>
          ) : (
            <>Each message fires a set number of hours <strong>after the lead replies</strong> — which is the moment
            their 24h window opens. A message at the Nth hour leaves <strong>24 − N</strong> hours of window.
            Freeform delivers inside the window; add a backup template to be safe near the edge.</>
          )}
        </p>
        <p className="mt-2 text-sm text-on-surface">
          Want to follow up after a day or more? Set the wait in <strong>days</strong> (up to {MAX_DELAY_DAYS}). Those
          steps always use an approved template, send only 10 AM–8 PM Mon–Sat, and reach a person at most once a day.
          People who already bought are skipped.
        </p>
      </div>

      {/* 24h timeline */}
      <div className="rounded-2xl border border-on-surface/10 p-5">
        <div className="mb-3 flex items-center justify-between">
          <span className="font-label text-xs uppercase tracking-widest text-on-surface-muted">
            {timelineMax > 24 ? "Timeline" : "24-hour window"}
          </span>
          <span className="text-xs text-on-surface-muted">
            {timelineMax > 24 ? `Red line = 24-hour window closes · up to ${formatDelay(timelineMax)}` : "0h → 24h close"}
          </span>
        </div>
        <div className="relative h-10 rounded-full bg-gradient-to-r from-emerald-100 to-emerald-50">
          <div
            className="absolute top-0 h-full w-px bg-red-300"
            style={{ left: `${(Math.min(24, timelineMax) / timelineMax) * 100}%` }}
          />
          {steps.map((s) => {
            const left = Math.min(100, (s.delay_hours / timelineMax) * 100);
            return (
              <div
                key={s.id}
                className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2"
                style={{ left: `${left}%` }}
                title={`${formatDelay(s.delay_hours)} · ${s.message_type}`}
              >
                <div className={`h-4 w-4 rounded-full border-2 border-white shadow ${s.message_type === "template" ? "bg-primary" : "bg-emerald-600"}`} />
                <span className="mt-1 block whitespace-nowrap text-xs text-on-surface-muted">{formatDelay(s.delay_hours)}</span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Step list */}
      <div className="space-y-3">
        {loading ? (
          <p className="text-sm text-on-surface-muted">Loading…</p>
        ) : steps.length === 0 ? (
          <p className="text-sm text-on-surface-muted">No messages yet. Add the first one below.</p>
        ) : (
          steps.map((s, i) => (
            <div key={s.id} className="rounded-xl border border-on-surface/10 bg-surface/40">
              <div className="flex items-start justify-between p-4">
                <div className="space-y-1">
                  <div className="flex items-center gap-2 text-sm font-semibold text-on-surface">
                    <span className="rounded bg-on-surface/10 px-2 py-0.5 text-xs">Step {i + 1}</span>
                    <span>{formatDelay(s.delay_hours)} {anchorLabel}</span>
                    <span className="text-on-surface-muted">·</span>
                    <span>{s.target_segments.map((x) => SEGMENT_LABELS[x] || x).join(", ")}</span>
                    {s.target_sources && s.target_sources.length > 0 && (
                      <>
                        <span className="text-on-surface-muted">·</span>
                        <span className="text-on-surface-muted">
                          {s.target_sources.map((x) => SOURCE_LABELS[x] || x).join(", ")}
                        </span>
                      </>
                    )}
                  </div>
                  <div className="text-xs text-on-surface-muted">
                    {s.message_type === "template" ? (
                      <>Template: <span className="font-mono">{s.template_name}</span> · {isDayStep(s.delay_hours) ? "sends 10 AM–8 PM, Mon–Sat" : "always delivers"}</>
                    ) : (
                      <>Freeform{s.fallback_template_name ? <> → backup template <span className="font-mono">{s.fallback_template_name}</span></> : <> · skipped if window closed</>}</>
                    )}
                  </div>
                  {s.message_type === "freeform" && s.message_content && (
                    <p className="max-w-xl truncate text-sm text-on-surface">&ldquo;{s.message_content}&rdquo;</p>
                  )}
                </div>
                <div className="flex items-center gap-3">
                  <button
                    onClick={() => setExpandedLog(expandedLog === s.id ? null : s.id)}
                    className="text-xs text-on-surface-muted hover:text-on-surface"
                  >
                    {expandedLog === s.id ? "Hide history" : "History"}
                  </button>
                  <button onClick={() => startEdit(s)} disabled={!canManage} className="text-xs text-on-surface hover:text-primary disabled:cursor-not-allowed disabled:opacity-40">
                    Edit
                  </button>
                  <button onClick={() => removeStep(s.id)} disabled={!canManage} className="text-xs text-red-500 hover:text-red-700 disabled:cursor-not-allowed disabled:opacity-40">
                    Remove
                  </button>
                </div>
              </div>
              {expandedLog === s.id && (
                <div className="border-t border-on-surface/10 px-4 pb-4">
                  <StepLogPanel stepId={s.id} />
                </div>
              )}
            </div>
          ))
        )}
      </div>

      {/* Add form */}
      {showAdd ? (
        <div className="space-y-4 rounded-2xl border border-on-surface/15 p-5">
          <div className="grid grid-cols-2 gap-4">
            <div role="group" aria-labelledby="delay-label">
              <span id="delay-label" className="font-label text-xs uppercase tracking-widest text-on-surface-muted">Wait</span>
              <div className="mt-1 flex gap-2">
                <input
                  type="number"
                  min={1}
                  max={delayUnit === "days" ? MAX_DELAY_DAYS : MAX_DELAY_HOURS}
                  aria-label="Wait time"
                  value={delayValue}
                  onChange={(e) => changeDelay(Number(e.target.value) || 1, delayUnit)}
                  className="w-24 rounded-xl border border-on-surface/20 px-3 py-2"
                />
                <Select
                  aria-label="Hours or days"
                  value={delayUnit}
                  onChange={(v) => changeDelay(delayValue, v as DelayUnit)}
                  className="w-28"
                  options={[
                    { value: "hours", label: "Hours" },
                    { value: "days", label: "Days" },
                  ]}
                />
              </div>
              {delayHours === null && (
                <p className="mt-1 text-xs text-red-600">Use a whole number, up to {MAX_DELAY_DAYS} days.</p>
              )}
            </div>
            <div role="group" aria-labelledby="seg-label">
              <span id="seg-label" className="font-label text-xs uppercase tracking-widest text-on-surface-muted">Target segments</span>
              <div className="mt-1 flex gap-2">
                {SEGMENTS.map((s) => (
                  <button
                    key={s}
                    type="button"
                    aria-pressed={segments.includes(s)}
                    onClick={() => toggleSegment(s)}
                    className={`rounded-full px-3 py-1 text-xs ${segments.includes(s) ? "bg-on-surface text-surface" : "bg-on-surface/10 text-on-surface"}`}
                  >
                    {SEGMENT_LABELS[s]}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div role="group" aria-labelledby="src-label">
            <span id="src-label" className="font-label text-xs uppercase tracking-widest text-on-surface-muted">
              Lead sources
            </span>
            <p className="mb-1 mt-0.5 text-xs text-on-surface-muted">
              Leave all off to include every source.
            </p>
            <div className="flex flex-wrap gap-2">
              {SOURCES.map((s) => (
                <button
                  key={s}
                  type="button"
                  aria-pressed={sources.includes(s)}
                  onClick={() => toggleSource(s)}
                  className={`rounded-full px-3 py-1 text-xs ${sources.includes(s) ? "bg-on-surface text-surface" : "bg-on-surface/10 text-on-surface"}`}
                >
                  {SOURCE_LABELS[s]}
                </button>
              ))}
            </div>
          </div>

          <div className="flex gap-2">
            <button
              type="button"
              aria-pressed={messageType === "freeform"}
              disabled={dayStep}
              title={dayStep ? "After 24 hours WhatsApp only allows an approved template" : undefined}
              onClick={() => setMessageType("freeform")}
              className={`rounded-xl px-4 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-40 ${messageType === "freeform" ? "bg-on-surface text-surface" : "bg-on-surface/10 text-on-surface"}`}
            >
              Freeform (window only)
            </button>
            <button
              type="button"
              aria-pressed={messageType === "template"}
              onClick={() => setMessageType("template")}
              className={`rounded-xl px-4 py-2 text-sm ${messageType === "template" ? "bg-on-surface text-surface" : "bg-on-surface/10 text-on-surface"}`}
            >
              Approved template (always sent)
            </button>
          </div>

          {dayStep && (
            <p className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">{DAY_STEP_NOTE}</p>
          )}

          {messageType === "freeform" ? (
            <>
              <textarea
                value={content}
                onChange={(e) => setContent(e.target.value)}
                placeholder="Hi! We noticed you haven't booked a time yet. Let us know if you have questions!"
                className="min-h-24 w-full rounded-xl border border-on-surface/20 px-3 py-2 text-sm"
              />
              <label className="block">
                <span className="font-label text-xs uppercase tracking-widest text-on-surface-muted">
                  Backup template (sent if the lead&apos;s window is closed)
                </span>
                <Select
                  value={fallbackTemplate}
                  onChange={setFallbackTemplate}
                  className="mt-1"
                  options={[
                    { value: "", label: "No backup — skip lead if window closed" },
                    ...templates.map((t) => {
                      const c = varCountByName[t.name] ?? 0;
                      return {
                        value: t.name,
                        label: `${t.name}${c >= 2 ? " (multi-variable — not supported)" : ""}`,
                        disabled: c >= 2,
                      };
                    }),
                  ]}
                />
              </label>
            </>
          ) : (
            <label className="block">
              <span className="font-label text-xs uppercase tracking-widest text-on-surface-muted">Template</span>
              <Select
                value={templateName}
                onChange={setTemplateName}
                placeholder="Select a template…"
                className="mt-1"
                options={templates.map((t) => {
                  const c = varCountByName[t.name] ?? 0;
                  return {
                    value: t.name,
                    label: `${t.name}${c >= 2 ? " (multi-variable — not supported)" : ""}`,
                    disabled: c >= 2,
                  };
                })}
              />
            </label>
          )}

          <div className="flex justify-end gap-2">
            <button onClick={cancelForm} className="rounded-xl px-4 py-2 text-sm text-on-surface-muted">
              Cancel
            </button>
            <button onClick={saveStep} disabled={!canManage} title={canManage ? "Save message" : "Read-only role: saving is disabled"} className="rounded-xl bg-on-surface px-5 py-2 text-sm text-surface disabled:cursor-not-allowed disabled:opacity-40 disabled:blur-[0.5px]">
              {editingId ? "Save changes" : "Save message"}
            </button>
          </div>
        </div>
      ) : (
        <button
          onClick={() => setShowAdd(true)}
          disabled={!canManage || (type === "broadcast" && !broadcastId)}
          className="w-full rounded-xl border-2 border-dashed border-on-surface/20 py-3 text-sm text-on-surface-muted hover:border-on-surface/40 disabled:opacity-40"
        >
          + Add message
        </button>
      )}
    </div>
  );
}
