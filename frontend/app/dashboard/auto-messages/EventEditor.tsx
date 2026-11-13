"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import {
  api,
  type AutoMessageRule,
  type AutoMessageTemplate,
  type AutoMessageVariable,
} from "@/lib/api";
import { Select } from "@/components/ui/Select";
import { CopyButton } from "@/app/dashboard/settings/connect-channels/ui";
import { CategoryTag } from "./CategoryTag";
import { DeleteEvent } from "./DeleteEvent";
import { PreviewSend } from "./PreviewSend";
import { VariableRow, defaultVariables, variableIsIncomplete } from "./VariableRow";
import { WhatsAppBubble } from "./WhatsAppBubble";
import { ghostBtn, inputCls, primaryBtn, sampleValue, type EventInfo } from "./shared";

const LABEL = "font-label text-xs font-bold text-ink";
const BLANK_RE = /\{\{\s*(\d+)\s*\}\}/g;

/** One entry per {{n}} in the body: what the rule already has, else the default for that slot. */
function fitVariables(count: number, current: AutoMessageVariable[]): AutoMessageVariable[] {
  const defaults = defaultVariables(count);
  return Array.from({ length: count }, (_, i) => current[i] ?? defaults[i]);
}

const EMPTY_BUTTON: AutoMessageVariable = { source: "text", value: "" };

interface Draft {
  templateId: string;
  variables: AutoMessageVariable[];
  buttonParam: AutoMessageVariable;
  label: string;
  description: string;
}

function initialDraft(ev: EventInfo, rule: AutoMessageRule | null, templates: AutoMessageTemplate[]): Draft {
  const template = rule ? templates.find((t) => t.id === rule.template_id) : undefined;
  return {
    templateId: template?.id ?? "",
    variables: template ? fitVariables(template.variable_count, rule?.variables ?? []) : [],
    buttonParam: rule?.button_param ?? EMPTY_BUTTON,
    label: ev.label,
    description: ev.description ?? "",
  };
}

/** Draft as text for "has anything changed?". */
function comparable(d: Draft): string {
  return JSON.stringify(d);
}

export interface EventEditorProps {
  ev: EventInfo;
  rule: AutoMessageRule | null;
  templates: AutoMessageTemplate[];
  canManage: boolean;
  panelId: string;
  pickerId: string;
  /** The unsaved-changes warning is showing because the owner tried to leave. */
  warnUnsaved: boolean;
  onDirtyChange: (dirty: boolean) => void;
  /** Saved: the parent reloads, shows "Saved" and moves on. */
  onSaved: () => void;
  /** Something changed on the server but the row stays open. */
  onChanged: () => void;
  onRequestClose: () => void;
  onDiscard: () => void;
  onKeepEditing: () => void;
  onDeleted: () => void;
}

function UnsavedWarning({
  saving,
  onSave,
  onDiscard,
  onKeep,
}: {
  saving: boolean;
  onSave: () => void;
  onDiscard: () => void;
  onKeep: () => void;
}) {
  return (
    <div role="alert" className="flex flex-wrap items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2">
      <p className="mr-auto font-body text-xs font-semibold text-amber-800">Unsaved changes.</p>
      <button type="button" onClick={onSave} disabled={saving} className={primaryBtn}>
        {saving ? "Saving…" : "Save"}
      </button>
      <button type="button" onClick={onDiscard} disabled={saving} className={ghostBtn}>
        Discard
      </button>
      <button type="button" onClick={onKeep} disabled={saving} className={ghostBtn}>
        Keep editing
      </button>
    </div>
  );
}

export function EventEditor(props: EventEditorProps) {
  const { ev, rule, templates, canManage, panelId, pickerId } = props;
  const [initial] = useState(() => initialDraft(ev, rule, templates));
  const [draft, setDraft] = useState<Draft>(initial);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showErrors, setShowErrors] = useState(false);

  useEffect(() => {
    document.getElementById(pickerId)?.focus();
  }, [pickerId]);

  const isDirty = comparable(draft) !== comparable(initial);
  const { onDirtyChange } = props;
  useEffect(() => {
    onDirtyChange(isDirty);
  }, [isDirty, onDirtyChange]);

  const template = templates.find((t) => t.id === draft.templateId) ?? null;
  const vars = template ? fitVariables(template.variable_count, draft.variables) : [];
  const buttonNeeded = Boolean(template?.has_dynamic_button);
  const metaChanged = ev.custom && (draft.label.trim() !== ev.label || draft.description.trim() !== (ev.description ?? ""));

  function patch(next: Partial<Draft>) {
    setDraft((d) => ({ ...d, ...next }));
  }

  function pickTemplate(id: string) {
    const t = templates.find((x) => x.id === id);
    patch({ templateId: id, variables: defaultVariables(t?.variable_count ?? 0), buttonParam: EMPTY_BUTTON });
  }

  function problems(): string | null {
    if (ev.custom && !draft.label.trim()) return "Give the event a name.";
    if (!template) return rule || !metaChanged ? "Pick a template." : null;
    if (vars.some(variableIsIncomplete) || (buttonNeeded && variableIsIncomplete(draft.buttonParam))) {
      return "Fill in the blanks marked above.";
    }
    return null;
  }

  async function saveRule(): Promise<void> {
    if (!template) return;
    const payload = {
      template_id: template.id,
      variables: vars,
      button_param: buttonNeeded ? draft.buttonParam : null,
    };
    if (rule) await api.autoMessages.updateRule(rule.id, payload);
    else await api.autoMessages.createRule({ ...payload, event: ev.key, enabled: true });
  }

  async function save() {
    setShowErrors(true);
    const problem = problems();
    if (problem) {
      setError(problem);
      return;
    }
    setSaving(true);
    setError(null);
    let ruleSaved = false;
    try {
      await saveRule();
      ruleSaved = Boolean(template);
      if (metaChanged) {
        await api.autoMessages.updateEvent(ev.key, { label: draft.label.trim(), description: draft.description.trim() });
      }
      props.onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save. Try again.");
      if (ruleSaved) props.onChanged();
    } finally {
      setSaving(false);
    }
  }

  const disabled = !canManage || saving;
  const preview = template
    ? template.body_text.replace(BLANK_RE, (_m, n: string) => {
        const v = vars[Number(n) - 1];
        return v ? sampleValue(v) : "…";
      })
    : "";

  return (
    <div
      id={panelId}
      role="group"
      aria-label={`${ev.label} message`}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          props.onRequestClose();
        }
      }}
      className="grid gap-5 border-t border-dashed border-primary/25 bg-primary-50/40 px-4 py-5 lg:grid-cols-[minmax(0,1fr)_300px]"
    >
      <div className="order-first lg:order-none lg:col-start-2 lg:row-start-1">
        {template ? (
          <WhatsAppBubble
            title="Priya will get"
            headerMedia={template.header_media_type}
            body={preview}
            buttons={template.buttons}
          />
        ) : (
          <div className="rounded-2xl border border-dashed border-border bg-white p-4 font-body text-xs text-ink-secondary">
            Pick a template to see what customers will get.
          </div>
        )}
      </div>

      <div className="min-w-0 space-y-5 lg:col-start-1 lg:row-start-1">
        {!canManage && (
          <p className="font-body text-xs text-ink-secondary">You can see this message, but only an admin can change it.</p>
        )}

        {ev.custom && (
          <section className="space-y-2">
            <label htmlFor={`${panelId}-name`} className={LABEL}>
              Name
            </label>
            <input
              id={`${panelId}-name`}
              value={draft.label}
              onChange={(e) => patch({ label: e.target.value })}
              maxLength={60}
              disabled={disabled}
              aria-invalid={showErrors && !draft.label.trim()}
              className={inputCls}
            />
            <label htmlFor={`${panelId}-when`} className={LABEL}>
              When does this happen? <span className="font-normal text-ink-secondary">(optional)</span>
            </label>
            <input
              id={`${panelId}-when`}
              value={draft.description}
              onChange={(e) => patch({ description: e.target.value })}
              maxLength={200}
              disabled={disabled}
              className={inputCls}
            />
            <div className="flex flex-wrap items-center gap-2 font-body text-xs text-ink-secondary">
              <span>
                Code your app sends: <span className="font-mono font-bold text-primary">{ev.key}</span>
              </span>
              {canManage && <CopyButton text={ev.key} label={`Copy code ${ev.key}`} />}
              <span className="text-ink-muted">The name can change. The code can&apos;t.</span>
            </div>
          </section>
        )}

        <section className="space-y-2">
          <label htmlFor={pickerId} className={LABEL}>
            Template
          </label>
          {templates.length === 0 ? (
            <p className="rounded-xl border border-amber-200 bg-amber-50 p-3 font-body text-xs text-amber-800">
              You have no approved templates yet.{" "}
              <Link href="/dashboard/templates" className="font-semibold underline">
                Create one under Templates
              </Link>
              .
            </p>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              <Select
                id={pickerId}
                value={draft.templateId}
                onChange={pickTemplate}
                disabled={disabled}
                placeholder="Choose a template…"
                className="min-w-0 flex-1 font-mono"
                options={templates.map((t) => ({
                  value: t.id,
                  label: `${t.name}${t.category ? ` · ${t.category.toLowerCase()}` : ""}`,
                }))}
              />
              {template && <CategoryTag category={template.category} />}
            </div>
          )}
          <p className="font-body text-[11px] text-ink-muted">
            Only templates Meta has approved show up. Utility costs less than Marketing.
          </p>
        </section>

        {template && (vars.length > 0 || buttonNeeded) && (
          <section className="space-y-2">
            <p className={LABEL}>Fill the blanks</p>
            {vars.map((v, i) => (
              <VariableRow
                key={i}
                label={`{{${i + 1}}}`}
                value={v}
                showErrors={showErrors}
                disabled={disabled}
                onChange={(next) => patch({ variables: vars.map((x, j) => (j === i ? next : x)) })}
              />
            ))}
            {buttonNeeded && (
              <>
                <p className="pt-1 font-body text-xs text-ink-secondary">
                  The end of the button&apos;s link. It is added after the web address in the template.
                </p>
                <VariableRow
                  label="Button"
                  value={draft.buttonParam}
                  showErrors={showErrors}
                  disabled={disabled}
                  onChange={(buttonParam) => patch({ buttonParam })}
                />
              </>
            )}
          </section>
        )}

        {canManage && props.warnUnsaved && (
          <UnsavedWarning saving={saving} onSave={save} onDiscard={props.onDiscard} onKeep={props.onKeepEditing} />
        )}

        {canManage && (
          <div className="space-y-2">
            <div className="flex flex-wrap items-start gap-2">
              <button type="button" onClick={save} disabled={saving || !isDirty} className={`${primaryBtn} max-sm:w-full`}>
                {saving ? "Saving…" : "Save"}
              </button>
              <button type="button" onClick={props.onRequestClose} disabled={saving} className={ghostBtn}>
                Cancel
              </button>
              <PreviewSend ruleId={rule?.id ?? null} isDirty={isDirty} />
            </div>
            {error && (
              <p role="alert" className="font-body text-xs font-semibold text-danger">
                {error}
              </p>
            )}
            {ev.custom && <DeleteEvent ev={ev} onDeleted={props.onDeleted} />}
          </div>
        )}
      </div>
    </div>
  );
}
