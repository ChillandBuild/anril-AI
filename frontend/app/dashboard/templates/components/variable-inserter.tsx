"use client";

import { useCallback, useEffect, useRef, useMemo, useState } from "react";
import { Bold, ChevronDown, Italic, Plus, Smile, UserPlus } from "lucide-react";
import { detectVariables } from "../types";
import { insertAt, toggleWrap } from "../template-format";
import type { EditResult } from "../template-format";
import { CUSTOMER_DETAILS, DETAIL_GROUP_TITLES, nextVarNumber, variableChip } from "../template-details";
import type { CustomerDetail, DetailGroup } from "../template-details";
import { bodyBlockers, renumberVariables, shortTemplateTip, sampleBlockers, tidyVariables } from "../template-rules";
import FieldMessages, { SampleInputs, useFixNotes } from "./field-messages";

type VariableInserterProps = {
  value: string;
  onChange: (value: string) => void;
  samples: Record<number, string>;
  onSamplesChange: (samples: Record<number, string>) => void;
  placeholder?: string;
  maxLength?: number;
  rows?: number;
  label: string;
  helperText?: string;
  /** id of the textarea; sample inputs are `${id}-sample-${n}` */
  id?: string;
};

/* ── helpers ─────────────────────────────────────────────────── */

const EMOJIS = [
  "🙏", "😊", "👍", "🎉", "❤️", "✅", "🎁", "🛍️",
  "📦", "🚚", "💰", "📅", "⏰", "📞", "📍", "⭐",
  "🔥", "🌟", "🙌", "👋", "😀", "🎊", "🪔", "💐",
];

const TOOL_BTN =
  "inline-flex h-8 min-w-8 items-center justify-center gap-1 rounded-lg border border-border-subtle bg-white px-2 text-xs font-medium text-ink-secondary transition-colors hover:border-border hover:bg-surface-subtle focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary-600";

type Menu = "detail" | "emoji" | null;

/* ── component ───────────────────────────────────────────────── */

export default function VariableInserter({
  value,
  onChange,
  samples,
  onSamplesChange,
  placeholder = "Type your message here…",
  maxLength = 1024,
  rows = 4,
  label,
  helperText,
  id = "template-body",
}: VariableInserterProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const toolbarRef = useRef<HTMLDivElement>(null);
  const { notes, show } = useFixNotes();
  const [menu, setMenu] = useState<Menu>(null);
  // Plain-words name for each {{n}} the owner added from the picker. Only a note for the owner:
  // the template sent to Meta is unchanged, so this is not saved.
  const [labels, setLabels] = useState<Record<number, string>>({});

  const variables = useMemo(() => detectVariables(value), [value]);
  const blockers = useMemo(() => bodyBlockers(value, id).filter((b) => b.inline), [value, id]);
  const tip = useMemo(() => (blockers.length ? null : shortTemplateTip(value)), [value, blockers]);
  const missingSamples = useMemo(() => sampleBlockers(value, samples, `${id}-sample-`), [value, samples, id]);
  const messagesId = `${id}-messages`;

  // A label only belongs to a variable that is still in the text.
  useEffect(() => {
    setLabels((prev) => {
      const keys = Object.keys(prev).map(Number);
      if (keys.every((n) => variables.includes(n))) return prev;
      return Object.fromEntries(Object.entries(prev).filter(([n]) => variables.includes(Number(n))));
    });
  }, [variables]);

  // Close the open pop-up on a click elsewhere.
  useEffect(() => {
    if (!menu) return;
    const onDown = (e: MouseEvent) => {
      if (toolbarRef.current && !toolbarRef.current.contains(e.target as Node)) setMenu(null);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [menu]);

  const chip = useCallback((n: number) => variableChip(n, labels), [labels]);

  function handleChange(next: string) {
    const tidied = tidyVariables(next);
    show("body", tidied.note);
    onChange(tidied.text);
  }

  function renumber() {
    const { text, moved } = renumberVariables(value);
    const nextSamples: Record<number, string> = {};
    Object.entries(moved).forEach(([oldN, newN]) => {
      nextSamples[newN] = samples[Number(oldN)] ?? "";
    });
    const nextLabels: Record<number, string> = {};
    Object.entries(moved).forEach(([oldN, newN]) => {
      if (labels[Number(oldN)]) nextLabels[newN] = labels[Number(oldN)];
    });
    setLabels(nextLabels);
    onChange(text);
    onSamplesChange(nextSamples);
    show("body", "Renumbered the variables in order. Your samples moved with them.");
  }

  /** Apply an edit to the textarea, then put the cursor where the edit says. */
  function apply(result: EditResult | null) {
    const el = textareaRef.current;
    if (!result) {
      show("body", `That would go over ${maxLength} letters, so nothing was added.`);
      return;
    }
    onChange(tidyVariables(result.value).text);
    requestAnimationFrame(() => {
      if (!el) return;
      el.focus();
      el.setSelectionRange(result.selStart, result.selEnd);
    });
  }

  function cursor(): [number, number] {
    const el = textareaRef.current;
    return [el?.selectionStart ?? value.length, el?.selectionEnd ?? value.length];
  }

  /** Raw {{n}} at the cursor, for anyone who wants to decide later what it means. */
  function insertVariable() {
    const [start, end] = cursor();
    const num = nextVarNumber(variables);
    apply(insertAt(value, start, end, `{{${num}}}`, maxLength));
    setMenu(null);
  }

  /** The next {{n}} at the cursor, plus its sample and its plain-words label. */
  function insertDetail(detail: CustomerDetail) {
    const [start, end] = cursor();
    const num = nextVarNumber(variables);
    const result = insertAt(value, start, end, `{{${num}}}`, maxLength);
    if (result) {
      onSamplesChange({ ...samples, [num]: detail.sample });
      setLabels((prev) => ({ ...prev, [num]: detail.label }));
    }
    apply(result);
    setMenu(null);
  }

  function format(marker: "*" | "_") {
    const [start, end] = cursor();
    apply(toggleWrap(value, start, end, marker, maxLength));
  }

  function insertEmoji(emoji: string) {
    const [start, end] = cursor();
    apply(insertAt(value, start, end, emoji, maxLength));
    setMenu(null);
  }

  function onToolbarKey(e: React.KeyboardEvent) {
    if (e.key === "Escape" && menu) {
      e.stopPropagation();
      setMenu(null);
      textareaRef.current?.focus();
    }
  }

  return (
    <div>
      {/* Label */}
      <label htmlFor={id} className="font-body text-sm font-medium text-ink mb-1.5 block">
        {label}
      </label>

      {/* Toolbar: bold, italic, emoji, customer detail */}
      <div
        ref={toolbarRef}
        onKeyDown={onToolbarKey}
        className="relative mb-1.5 flex flex-wrap items-center gap-1.5"
      >
        <button
          type="button"
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => format("*")}
          aria-label="Bold: wrap the selected words in stars"
          title="Bold"
          className={TOOL_BTN}
        >
          <Bold size={14} />
        </button>
        <button
          type="button"
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => format("_")}
          aria-label="Italic: wrap the selected words in underscores"
          title="Italic"
          className={TOOL_BTN}
        >
          <Italic size={14} />
        </button>
        <button
          type="button"
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => setMenu(menu === "emoji" ? null : "emoji")}
          aria-label="Add an emoji"
          aria-haspopup="true"
          aria-expanded={menu === "emoji"}
          title="Emoji"
          className={TOOL_BTN}
        >
          <Smile size={14} />
        </button>

        <span className="mx-0.5 h-5 w-px bg-border-subtle" aria-hidden="true" />

        <button
          type="button"
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => setMenu(menu === "detail" ? null : "detail")}
          aria-label="Add a customer detail, like the customer's name"
          aria-haspopup="true"
          aria-expanded={menu === "detail"}
          className={`${TOOL_BTN} text-primary-700`}
        >
          <UserPlus size={14} />
          Customer detail
          <ChevronDown size={12} />
        </button>
        <button
          type="button"
          onMouseDown={(e) => e.preventDefault()}
          onClick={insertVariable}
          aria-label="Add a blank numbered variable, for example {{1}}"
          className={TOOL_BTN}
        >
          <Plus size={12} />
          Blank {"{{n}}"}
        </button>
        {helperText && <p className="font-body text-xs text-ink-secondary">{helperText}</p>}

        {menu === "emoji" && (
          <div
            role="group"
            aria-label="Pick an emoji"
            className="absolute left-0 top-full z-20 mt-1 grid w-[17rem] grid-cols-8 gap-1 rounded-xl border border-border-subtle bg-white p-2 shadow-lg"
          >
            {EMOJIS.map((emoji) => (
              <button
                key={emoji}
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => insertEmoji(emoji)}
                aria-label={`Add ${emoji}`}
                className="flex h-8 w-8 items-center justify-center rounded-lg text-lg hover:bg-surface-subtle focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary-600"
              >
                {emoji}
              </button>
            ))}
          </div>
        )}

        {menu === "detail" && (
          <div
            role="group"
            aria-label="Pick a customer detail"
            className="absolute left-0 top-full z-20 mt-1 max-h-[60dvh] w-[min(22rem,100%)] overflow-y-auto rounded-xl border border-border-subtle bg-white p-2 shadow-lg"
          >
            {(["filled", "supplied"] as DetailGroup[]).map((group) => (
              <div key={group} className="mb-1 last:mb-0">
                <p className="px-2 pb-1 pt-1.5 font-body text-xs font-semibold text-ink">{DETAIL_GROUP_TITLES[group]}</p>
                {CUSTOMER_DETAILS.filter((d) => d.group === group).map((d) => (
                  <button
                    key={d.id}
                    type="button"
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => insertDetail(d)}
                    aria-label={`Add ${d.label}, example ${d.sample}`}
                    className="flex w-full flex-col rounded-lg px-2 py-1.5 text-left hover:bg-surface-subtle focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary-600"
                  >
                    <span className="font-body text-sm font-medium text-ink">
                      {d.label} <span className="font-normal text-ink-secondary">e.g. {d.sample}</span>
                    </span>
                    <span className="font-body text-xs text-ink-secondary">{d.hint}</span>
                  </button>
                ))}
              </div>
            ))}
            <p className="border-t border-border-subtle px-2 pt-2 font-body text-xs text-ink-secondary">
              The example is only for Meta&apos;s review and is never sent. When you send, you choose what fills each blank.
            </p>
          </div>
        )}
      </div>

      {/* Textarea */}
      <textarea
        id={id}
        ref={textareaRef}
        value={value}
        onChange={(e) => handleChange(e.target.value)}
        placeholder={placeholder}
        rows={rows}
        maxLength={maxLength}
        aria-describedby={messagesId}
        aria-invalid={blockers.length > 0}
        className={`input resize-y min-h-[100px] text-sm ${
          blockers.length ? "border-red-400 focus:border-red-500" : ""
        }`}
      />

      {/* Footer: char count + detected vars */}
      <div className="flex items-center justify-between mt-1.5 flex-wrap gap-2">
        {/* Character count */}
        <p className="font-body text-xs text-ink-secondary">
          <span
            className={
              value.length > maxLength * 0.9
                ? "text-amber-600 font-medium"
                : ""
            }
          >
            {value.length}
          </span>
          /{maxLength}
        </p>

        {/* Detected variables */}
        {variables.length > 0 && (
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="font-body text-xs text-ink-secondary">Example values:</span>
            {variables.map((v) => (
              <span
                key={v}
                className="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-semibold"
                style={{ background: "var(--primary-50)", color: "var(--primary-900)" }}
              >
                {chip(v)}
              </span>
            ))}
          </div>
        )}
      </div>

      <FieldMessages
        id={messagesId}
        note={notes.body}
        blockers={blockers}
        tip={tip}
        onFix={(fix) => fix === "renumber" && renumber()}
      />

      {blockers.length === 0 && (
        <>
          <SampleInputs
            variables={variables}
            samples={samples}
            onChange={onSamplesChange}
            idPrefix={`${id}-sample-`}
            chipLabel={chip}
          />
          <FieldMessages id={`${id}-sample-messages`} blockers={missingSamples} />
        </>
      )}
    </div>
  );
}
