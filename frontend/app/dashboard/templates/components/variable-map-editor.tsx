"use client";

import { useEffect, useMemo, useState } from "react";
import { Check, RotateCcw, SlidersHorizontal } from "lucide-react";
import { API_URL, getAuthHeaders } from "@/lib/api";
import { detectVariables } from "../types";
import { Select } from "@/components/ui/Select";

export type VariableMap = Record<string, string>;

const COLLECTED = "collected:";
const COLLECTED_OPTION = "__collected__";

// Keep in sync with FIELDS in backend/app/services/template_fields.py.
const FIELD_GROUPS: { label: string; fields: { value: string; label: string }[] }[] = [
  {
    label: "Lead",
    fields: [
      { value: "lead_name", label: "Lead name" },
      { value: "lead_phone", label: "Lead phone" },
      { value: "chat_link", label: "Chat link" },
      { value: "lead_source", label: "Lead source" },
      { value: "enquiry_date", label: "Enquiry date" },
      { value: "last_message", label: "Last message from lead" },
      { value: "channel", label: "Channel" },
      { value: "call_status", label: "Last call status" },
      { value: "assigned_agent", label: "Assigned agent" },
    ],
  },
  {
    label: "Alert",
    fields: [
      { value: "escalation_reason", label: "Escalation reason (escalation alerts)" },
      { value: "lead_temperature", label: "Hot / Warm label (hot-lead alerts)" },
      { value: "alert_time", label: "Alert date & time" },
    ],
  },
  { label: "Business", fields: [{ value: "business_name", label: "Business name" }] },
];

const FIELD_LABELS: Record<string, string> = Object.fromEntries(
  FIELD_GROUPS.flatMap((g) => g.fields.map((f) => [f.value, f.label.replace(/ \(.*\)$/, "")])),
);

// What each slot gets today when nothing is chosen (whatsapp_notify.py fixed order).
const DEFAULTS: Record<number, string> = {
  1: "Lead name",
  2: "Lead phone",
  3: "Escalation reason, or Hot / Warm label on hot-lead alerts",
  4: "Chat link",
  5: "Lead source (escalation alerts)",
};

export function fieldLabel(field: string): string {
  if (field.startsWith(COLLECTED)) return field.slice(COLLECTED.length) || "Collected detail";
  return FIELD_LABELS[field] || field;
}

type Props = {
  templateId: string;
  bodyText: string;
  saved: VariableMap | null | undefined;
  canEdit: boolean;
  onDraftChange: (draft: VariableMap) => void;
  onSaved: (map: VariableMap) => void;
};

export default function VariableMapEditor({ templateId, bodyText, saved, canEdit, onDraftChange, onSaved }: Props) {
  const slots = useMemo(() => detectVariables(bodyText).sort((a, b) => a - b), [bodyText]);
  // Keyed on content so a parent re-render with an equal map doesn't wipe unsaved choices.
  const savedKey = JSON.stringify(saved || {});
  const savedMap = useMemo<VariableMap>(() => JSON.parse(savedKey), [savedKey]);
  const [draft, setDraft] = useState<VariableMap>(savedMap);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [justSaved, setJustSaved] = useState(false);

  useEffect(() => setDraft(savedMap), [savedMap]);
  useEffect(() => onDraftChange(draft), [draft, onDraftChange]);

  const dirty = JSON.stringify(normalize(draft)) !== JSON.stringify(normalize(savedMap));
  const missingKey = slots.find((n) => draft[n] === COLLECTED);

  function setSlot(n: number, value: string) {
    setJustSaved(false);
    setDraft((d) => {
      const next = { ...d };
      if (!value) delete next[n];
      else next[n] = value;
      return next;
    });
  }

  async function save(map: VariableMap) {
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(`${API_URL}/api/v1/templates/${templateId}/variable-map`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...(await getAuthHeaders()) },
        body: JSON.stringify({ variable_map: normalize(map) }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail || "Couldn't save the variables");
      }
      const data = await res.json();
      onSaved(data.variable_map || {});
      setJustSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the variables");
    } finally {
      setSaving(false);
    }
  }

  if (!slots.length) return null;

  return (
    <div className="bg-white rounded-3xl border border-border-subtle p-6 shadow-sm">
      <div className="flex items-start justify-between gap-4 border-b border-border-subtle pb-3">
        <div className="flex items-start gap-3">
          <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-primary-50 text-primary-700">
            <SlidersHorizontal size={15} />
          </span>
          <div>
            <h2 className="font-display text-base font-bold text-ink">Variables</h2>
            <p className="font-body text-xs text-ink-muted mt-0.5 leading-relaxed">
              Choose what fills each placeholder when this template goes out as an escalation or hot-lead WhatsApp
              alert. Leave one on Default to keep what Anril sends today. Broadcasts and auto-messages pick their own.
            </p>
          </div>
        </div>
        {canEdit && Object.keys(savedMap).length > 0 && (
          <button
            onClick={() => save({})}
            disabled={saving}
            className="btn-ghost flex shrink-0 items-center gap-1 text-xs"
            title="Go back to the fixed order for every placeholder"
          >
            <RotateCcw size={12} /> Reset to default
          </button>
        )}
      </div>

      <div className="divide-y divide-border-subtle">
        {slots.map((n) => {
          const value = draft[n] || "";
          const isCollected = value.startsWith(COLLECTED);
          return (
            <div key={n} className="grid grid-cols-[3.25rem_1fr] items-start gap-3 py-3">
              <span
                className="mt-2 inline-flex justify-center rounded-md px-1.5 py-0.5 font-mono text-xs font-semibold"
                style={{ background: "var(--primary-50)", color: "var(--primary-900)" }}
              >
                {`{{${n}}}`}
              </span>
              <div className="space-y-2 min-w-0">
                <Select
                  aria-label={`What fills {{${n}}}`}
                  value={isCollected ? COLLECTED_OPTION : value}
                  disabled={!canEdit || saving}
                  onChange={(v) => setSlot(n, v === COLLECTED_OPTION ? COLLECTED : v)}
                  options={[
                    { value: "", label: `Default: ${DEFAULTS[n] || "a dash (-)"}` },
                    ...FIELD_GROUPS.flatMap((g) =>
                      g.fields.map((f) => ({ value: f.value, label: f.label, group: g.label })),
                    ),
                    { value: COLLECTED_OPTION, label: "Collected detail…", group: "From the chat" },
                  ]}
                />
                {isCollected && (
                  <input
                    aria-label={`Collected detail name for {{${n}}}`}
                    value={value.slice(COLLECTED.length)}
                    disabled={!canEdit || saving}
                    onChange={(e) => setSlot(n, COLLECTED + e.target.value.replace(/[^A-Za-z0-9_ .-]/g, "").slice(0, 64))}
                    placeholder="Detail name, e.g. course or city"
                    className="input w-full"
                    autoFocus
                  />
                )}
              </div>
            </div>
          );
        })}
      </div>

      {error && <p className="mt-2 font-body text-xs text-red-600">{error}</p>}

      {canEdit && (
        <div className="flex items-center justify-end gap-3 pt-3 border-t border-border-subtle">
          {missingKey && (
            <p className="mr-auto font-body text-xs text-ink-muted">Type the detail name for {`{{${missingKey}}}`}.</p>
          )}
          {justSaved && !dirty && (
            <span className="inline-flex items-center gap-1 font-body text-xs font-semibold text-emerald-600">
              <Check size={13} /> Saved
            </span>
          )}
          <button
            onClick={() => save(draft)}
            disabled={!dirty || saving || !!missingKey}
            className="btn-primary px-5 py-1.5 text-xs disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {saving ? "Saving…" : "Save variables"}
          </button>
        </div>
      )}
    </div>
  );
}

function normalize(map: VariableMap): VariableMap {
  return Object.fromEntries(
    Object.entries(map)
      .filter(([, v]) => v && v !== COLLECTED)
      .sort(([a], [b]) => Number(a) - Number(b)),
  );
}
