"use client";
import Link from "next/link";
import { ChevronDown, Plus } from "lucide-react";
import type { AutoMessageRule, AutoMessageTemplate } from "@/lib/api";
import { SwitchPill } from "@/components/ui/controls";
import { CategoryTag } from "./CategoryTag";
import { EventEditor, type EventEditorProps } from "./EventEditor";
import { focusRing, ghostBtn, nobodyLine, type EventInfo } from "./shared";

export const rowId = (key: string) => `event-row-${key}`;
const panelId = (key: string) => `event-panel-${key}`;
const pickerId = (key: string) => `event-picker-${key}`;

type EditorCallbacks = Pick<
  EventEditorProps,
  "onDirtyChange" | "onSaved" | "onChanged" | "onRequestClose" | "onDiscard" | "onKeepEditing" | "onDeleted"
>;

export interface EventRowProps extends EditorCallbacks {
  ev: EventInfo;
  rule: AutoMessageRule | null;
  template: AutoMessageTemplate | null;
  /** Name of the template a broken rule used, when we could look it up. */
  lostTemplateName: string | null;
  templates: AutoMessageTemplate[];
  canManage: boolean;
  /** At least one approved template exists, so a message can be added. */
  canAdd: boolean;
  open: boolean;
  justSaved: boolean;
  switching: boolean;
  warnUnsaved: boolean;
  onToggleOpen: () => void;
  onToggleEnabled: (next: boolean) => void;
}

function Summary({ rule, template, ev }: { rule: AutoMessageRule | null; template: AutoMessageTemplate | null; ev: EventInfo }) {
  if (!rule) return <span className="font-body text-sm text-ink-secondary">{nobodyLine(ev)}</span>;
  if (!rule.template_approved || !template) {
    return <span className="font-body text-sm text-amber-800">Needs a new template</span>;
  }
  return (
    <span className="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1 font-body text-sm text-ink-secondary">
      <span className="truncate font-mono text-[13px] font-semibold text-ink">{template.name}</span>
      <span aria-hidden>·</span>
      <CategoryTag category={template.category} />
    </span>
  );
}

export function EventRow(props: EventRowProps) {
  const { ev, rule, template, canManage, canAdd, open } = props;
  const broken = Boolean(rule) && (!rule?.template_approved || !template);
  const isOn = Boolean(rule?.enabled) && !broken;
  const expandable = Boolean(rule) || (canManage && canAdd);
  const waiting = Boolean(rule) && isOn && !rule?.has_sent;

  const hint = ev.custom ? ev.description || `code: ${ev.key}` : ev.description;
  const nameBlock = (
    <span className="min-w-0">
      <span className="flex items-center gap-2">
        <span className="font-display text-sm font-bold text-ink">{ev.label}</span>
        {ev.custom && (
          <span className="rounded-full border border-primary/20 bg-primary-50 px-2 py-0.5 font-label text-[10px] font-bold text-primary">
            Yours
          </span>
        )}
      </span>
      {hint && <span className="mt-0.5 block font-body text-xs text-ink-secondary">{hint}</span>}
    </span>
  );
  const headerClass = `flex min-w-0 flex-1 flex-col gap-1.5 rounded-lg py-1 text-left sm:grid sm:grid-cols-[minmax(0,230px)_minmax(0,1fr)] sm:items-center sm:gap-4 ${focusRing}`;

  return (
    <li className={`border-t border-border-subtle first:border-t-0 ${open ? "bg-primary-50/40" : ""}`}>
      <div className="flex items-center gap-2 px-3 py-2 sm:px-4">
        {expandable ? (
          <button
            id={rowId(ev.key)}
            type="button"
            aria-expanded={open}
            aria-controls={panelId(ev.key)}
            onClick={props.onToggleOpen}
            className={headerClass}
          >
            {nameBlock}
            <span className="min-w-0 max-sm:hidden">
              <Summary rule={rule} template={template} ev={ev} />
            </span>
          </button>
        ) : (
          <div className={headerClass.replace(focusRing, "")}>
            {nameBlock}
            <span className="min-w-0 max-sm:hidden">
              <Summary rule={rule} template={template} ev={ev} />
            </span>
          </div>
        )}

        <span role="status" className="shrink-0 font-label text-xs font-bold text-emerald-700">
          {props.justSaved ? "Saved" : ""}
        </span>

        {rule && canManage && (
          <span className="flex shrink-0 items-center justify-center max-sm:min-h-10 max-sm:min-w-10">
            <SwitchPill
              size="sm"
              on={isOn}
              loading={props.switching}
              disabled={broken}
              onChange={props.onToggleEnabled}
              aria-label={`${ev.label} message, ${isOn ? "on" : "off"}`}
            />
          </span>
        )}
        {rule && !canManage && (
          <span className="shrink-0 font-label text-xs font-bold text-ink-secondary">{isOn ? "On" : "Off"}</span>
        )}
        {!rule && canManage && (
          <button
            type="button"
            onClick={props.onToggleOpen}
            disabled={!canAdd}
            title={canAdd ? undefined : "You need an approved WhatsApp template first."}
            aria-label={`Add message for ${ev.label}`}
            className={`${ghostBtn} shrink-0`}
          >
            <Plus size={13} /> Add message
          </button>
        )}
        {expandable && (
          <button
            type="button"
            tabIndex={-1}
            aria-hidden
            onClick={props.onToggleOpen}
            className="flex shrink-0 items-center justify-center rounded-lg p-2 text-ink-muted max-sm:min-h-10 max-sm:min-w-10"
          >
            <ChevronDown size={16} className={`transition-transform ${open ? "rotate-180" : ""}`} />
          </button>
        )}
      </div>

      {/* Phones: the summary is a full-width second line under the name and controls. */}
      <div
        className="-mt-1 min-w-0 px-3 pb-3 sm:hidden"
        onClick={expandable ? props.onToggleOpen : undefined}
      >
        <Summary rule={rule} template={template} ev={ev} />
      </div>

      {broken && rule && (
        <p className="mx-3 mb-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 font-body text-xs text-amber-800 sm:mx-4">
          {props.lostTemplateName ? `Template '${props.lostTemplateName}'` : "This template"} lost approval. This message is off.{" "}
          <Link href="/dashboard/templates" className="font-semibold underline">
            Open Templates
          </Link>
        </p>
      )}

      {waiting && (
        <p className="mx-3 mb-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 font-body text-xs text-amber-800 sm:mx-4">
          Waiting for the first customer. Nothing fires <strong>{ev.label}</strong> yet.{" "}
          <a href="#get-customers-in" className="font-semibold underline">
            Connect your form or app ↓
          </a>
        </p>
      )}

      {open && (
        <EventEditor
          ev={ev}
          rule={rule}
          templates={props.templates}
          canManage={canManage}
          panelId={panelId(ev.key)}
          pickerId={pickerId(ev.key)}
          warnUnsaved={props.warnUnsaved}
          onDirtyChange={props.onDirtyChange}
          onSaved={props.onSaved}
          onChanged={props.onChanged}
          onRequestClose={props.onRequestClose}
          onDiscard={props.onDiscard}
          onKeepEditing={props.onKeepEditing}
          onDeleted={props.onDeleted}
        />
      )}
    </li>
  );
}
