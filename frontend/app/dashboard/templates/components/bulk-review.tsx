"use client";

import { AlertCircle, Check, RotateCcw, Trash2 } from "lucide-react";
import { Select } from "@/components/ui/Select";
import { LANGUAGES, languageName } from "../types";
import {
  BUTTON_KINDS,
  BUTTON_SLOTS,
  buttonSlots,
  issuesFor,
  previewOf,
  variablesIn,
  type BulkButton,
  type BulkResult,
  type BulkRow,
} from "../template-excel";
import WhatsAppPreview from "./whatsapp-preview";

export type RowFilter = "all" | "ready" | "need_fix" | "exists" | "removed";

const STATUS: Record<BulkRow["status"], { text: string; cls: string; dot: string }> = {
  ready: { text: "Ready", cls: "text-emerald-700", dot: "bg-emerald-500" },
  need_fix: { text: "Needs a fix", cls: "text-red-700", dot: "bg-red-500" },
  exists: { text: "Already exists", cls: "text-amber-800", dot: "bg-amber-500" },
};
const RESULT: Record<BulkResult["status"], { text: string; cls: string }> = {
  sent: { text: "Sent to Meta", cls: "bg-emerald-50 text-emerald-700" },
  refused: { text: "Meta refused", cls: "bg-red-50 text-red-700" },
  skipped: { text: "Not sent", cls: "bg-slate-100 text-slate-700" },
};

/* ── the list ────────────────────────────────────────────────── */

export function RowList({
  rows,
  removed,
  ticked,
  results,
  activeRow,
  onOpen,
  onTick,
  onRemove,
}: {
  rows: BulkRow[];
  removed: Set<number>;
  ticked: Set<number>;
  results: Map<number, BulkResult>;
  activeRow: number | null;
  onOpen: (row: number) => void;
  onTick: (row: number, on: boolean) => void;
  onRemove: (row: number, remove: boolean) => void;
}) {
  if (!rows.length) return <p className="px-4 py-10 text-center text-sm text-ink-muted">Nothing here.</p>;
  return (
    <ul className="divide-y divide-border-subtle">
      {rows.map((r) => {
        const isRemoved = removed.has(r.row);
        const result = results.get(r.row);
        const sent = result?.status === "sent";
        const st = STATUS[r.status];
        const canTick = !isRemoved && !sent && r.status === "ready";
        return (
          <li
            key={r.row}
            className={`group flex items-start gap-2.5 px-3 py-2.5 transition-colors ${
              activeRow === r.row ? "bg-primary-50/70" : "hover:bg-surface-subtle/60"
            } ${isRemoved ? "opacity-50" : ""}`}
          >
            <input
              type="checkbox"
              aria-label={`Send row ${r.row}`}
              className="mt-1 h-4 w-4 shrink-0 accent-[var(--primary-700,#038285)] disabled:opacity-30"
              checked={canTick && ticked.has(r.row)}
              disabled={!canTick}
              onChange={(e) => onTick(r.row, e.target.checked)}
            />
            <button type="button" onClick={() => onOpen(r.row)} className="min-w-0 flex-1 text-left">
              <span className="flex items-baseline gap-2">
                <span className="w-6 shrink-0 text-right text-[11px] tabular-nums text-ink-muted">{r.row}</span>
                <span className={`truncate font-mono text-[13px] font-semibold text-ink ${isRemoved ? "line-through" : ""}`}>
                  {r.name || "(no name)"}
                </span>
              </span>
              <span className="ml-8 mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[12px]">
                <span className="text-ink-muted">
                  {r.type ? r.type.charAt(0) + r.type.slice(1).toLowerCase() : "No type"} · {r.language ? languageName(r.language) : "No language"}
                </span>
                {result ? (
                  <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${RESULT[result.status].cls}`}>{RESULT[result.status].text}</span>
                ) : isRemoved ? (
                  <span className="text-ink-muted">Removed</span>
                ) : (
                  <span className={`inline-flex items-center gap-1 font-semibold ${st.cls}`}>
                    <span className={`h-1.5 w-1.5 rounded-full ${st.dot}`} />
                    {st.text}
                  </span>
                )}
              </span>
              {!isRemoved && !result && r.status === "need_fix" && (
                <span className="ml-8 mt-0.5 block truncate text-[12px] text-red-700">{r.problems[0]}</span>
              )}
              {result?.reason && result.status !== "sent" && (
                <span className="ml-8 mt-0.5 block text-[12px] text-red-700">{result.reason}</span>
              )}
            </button>
            {!sent && (
              <button
                type="button"
                onClick={() => onRemove(r.row, !isRemoved)}
                aria-label={isRemoved ? `Put row ${r.row} back` : `Remove row ${r.row}`}
                title={isRemoved ? "Put back" : "Remove from this upload"}
                className="mt-0.5 rounded-lg p-1.5 text-ink-muted transition hover:bg-red-50 hover:text-red-600"
              >
                {isRemoved ? <RotateCcw size={14} /> : <Trash2 size={14} />}
              </button>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/* ── the editor ──────────────────────────────────────────────── */

function FieldError({ texts }: { texts: string[] }) {
  if (!texts.length) return null;
  return (
    <p className="mt-1 flex items-start gap-1 text-[12px] text-red-700">
      <AlertCircle size={12} className="mt-0.5 shrink-0" aria-hidden="true" /> {texts.join(" ")}
    </p>
  );
}

const inputCls = (bad: boolean) =>
  `w-full rounded-xl border bg-white px-3 py-2 text-[13.5px] text-ink placeholder:text-[#94a3b8] focus:outline-none focus:ring-2 ${
    bad ? "border-red-300 focus:ring-red-100" : "border-[#e2e8f0] focus:border-primary-300 focus:ring-primary-100"
  }`;

function Field({ label, hint, errors, children }: { label: string; hint?: string; errors: string[]; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 flex items-baseline justify-between gap-2">
        <span className="text-[12.5px] font-semibold text-ink">{label}</span>
        {hint && <span className="text-[11.5px] text-ink-muted">{hint}</span>}
      </span>
      {children}
      <FieldError texts={errors} />
    </label>
  );
}

export function RowEditor({
  row,
  locked,
  removed,
  onChange,
}: {
  row: BulkRow;
  /** Sent already: shown, not editable. */
  locked: boolean;
  removed: boolean;
  onChange: (next: BulkRow) => void;
}) {
  const set = (patch: Partial<BulkRow>) => onChange({ ...row, ...patch });
  const used = variablesIn(row.body).filter((n) => n >= 1 && n <= row.examples.length);
  const headerVar = variablesIn(row.header).length > 0;
  const slots = buttonSlots(row);
  const setButton = (i: number, patch: Partial<BulkButton>) => {
    const next = slots.map((b, j) => (j === i ? { ...b, ...patch } : b));
    set({ buttons: next });
  };
  const disabled = locked || removed;
  const exists = row.status === "exists";

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_300px]">
      <fieldset disabled={disabled} className="min-w-0 space-y-3.5 disabled:opacity-70">
        {exists && (
          <p className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-[12.5px] text-amber-900">
            A template with this name and language is already on your account, so this row is skipped. Change the name to send it as a new template.
          </p>
        )}
        <Field label="Template name" hint="small letters, numbers and _" errors={exists ? [] : issuesFor(row, "name")}>
          <input className={`${inputCls(!exists && issuesFor(row, "name").length > 0)} font-mono`} value={row.name} onChange={(e) => set({ name: e.target.value })} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Type" errors={issuesFor(row, "type")}>
            <Select
              aria-label="Type"
              value={row.type ?? ""}
              onChange={(v) => set({ type: v })}
              placeholder="Pick a type"
              disabled={disabled}
              options={[{ value: "MARKETING", label: "Marketing" }, { value: "UTILITY", label: "Utility" }]}
            />
          </Field>
          <Field label="Language" errors={issuesFor(row, "language")}>
            <Select
              aria-label="Language"
              value={row.language ?? ""}
              onChange={(v) => set({ language: v })}
              placeholder="Pick a language"
              disabled={disabled}
              options={LANGUAGES.map((l) => ({ value: l.code, label: l.label }))}
            />
          </Field>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Header" hint="optional · up to 60" errors={issuesFor(row, "header")}>
            <input className={inputCls(issuesFor(row, "header").length > 0)} value={row.header} onChange={(e) => set({ header: e.target.value })} />
          </Field>
          {headerVar && (
            <Field label="Header example" hint="for {{1}}" errors={issuesFor(row, "header_example")}>
              <input className={inputCls(issuesFor(row, "header_example").length > 0)} value={row.header_example} onChange={(e) => set({ header_example: e.target.value })} />
            </Field>
          )}
        </div>
        <Field label="Body" hint={`${row.body.length} / 1024`} errors={issuesFor(row, "body")}>
          <textarea
            rows={4}
            className={`${inputCls(issuesFor(row, "body").length > 0)} resize-y`}
            value={row.body}
            onChange={(e) => set({ body: e.target.value })}
          />
        </Field>
        {used.length > 0 && (
          <div className="grid gap-3 sm:grid-cols-2">
            {used.map((n) => {
              const errs = issuesFor(row, `example_${n}`);
              return (
                <Field key={n} label={`Example {{${n}}}`} errors={errs}>
                  <input
                    className={inputCls(errs.length > 0)}
                    value={row.examples[n - 1] ?? ""}
                    placeholder="e.g. Priya"
                    onChange={(e) => set({ examples: row.examples.map((v, i) => (i === n - 1 ? e.target.value : v)) })}
                  />
                </Field>
              );
            })}
          </div>
        )}
        <Field label="Footer" hint="optional · up to 60" errors={issuesFor(row, "footer")}>
          <input className={inputCls(issuesFor(row, "footer").length > 0)} value={row.footer} onChange={(e) => set({ footer: e.target.value })} />
        </Field>
        <div>
          <span className="mb-1 block text-[12.5px] font-semibold text-ink">Buttons <span className="font-normal text-ink-muted">· optional, up to {BUTTON_SLOTS}</span></span>
          <div className="space-y-2">
            {slots.map((b, i) => {
              const errs = issuesFor(row, `button_${i + 1}`);
              return (
                <div key={i}>
                  <div className="grid grid-cols-[110px_minmax(0,1fr)] gap-2 sm:grid-cols-[120px_minmax(0,1fr)_minmax(0,1.3fr)]">
                    <Select
                      size="sm"
                      aria-label={`Button ${i + 1} type`}
                      value={b.type || "none"}
                      disabled={disabled}
                      onChange={(v) => setButton(i, v === "none" ? { type: "", text: "", value: "" } : { type: v as BulkButton["type"] })}
                      options={[{ value: "none", label: "No button" }, ...BUTTON_KINDS]}
                    />
                    <input
                      className={`${inputCls(errs.length > 0)} h-8 py-1`}
                      placeholder="Button text"
                      value={b.text}
                      disabled={!b.type || disabled}
                      onChange={(e) => setButton(i, { text: e.target.value })}
                    />
                    {b.type && b.type !== "QUICK_REPLY" && (
                      <input
                        className={`${inputCls(errs.length > 0)} col-span-2 h-8 py-1 sm:col-span-1`}
                        placeholder={b.type === "URL" ? "https://…" : "+91 98765 43210"}
                        value={b.value}
                        onChange={(e) => setButton(i, { value: e.target.value })}
                      />
                    )}
                  </div>
                  <FieldError texts={errs} />
                </div>
              );
            })}
          </div>
        </div>
      </fieldset>

      <div className="lg:sticky lg:top-0 lg:self-start">
        <p className="mb-2 text-[12px] font-semibold uppercase tracking-wider text-ink-muted">How it looks on WhatsApp</p>
        <WhatsAppPreview {...previewOf(row)} />
        {row.status === "ready" && !locked && !removed && (
          <p className="mt-2 flex items-center gap-1.5 text-[12.5px] font-medium text-emerald-700">
            <Check size={13} aria-hidden="true" /> Ready to send
          </p>
        )}
      </div>
    </div>
  );
}
