"use client";

import { Fragment } from "react";
import type { SmsVarSource } from "@/lib/api";
import { splitTemplate } from "./helpers";
import { Field, inputCls } from "./ui";

const FIXED = "__fixed__";

/** Wording with each {#var#} shown as a numbered chip, or as the chosen value once mapped. */
export function Wording({ message, map, fields }: { message: string; map?: (SmsVarSource | null)[]; fields?: { key: string; label: string }[] }) {
  return (
    <p className="whitespace-pre-wrap break-words text-sm text-[#334155]">
      {splitTemplate(message).map((part, i) => {
        if (part.kind === "text") return <Fragment key={i}>{part.text}</Fragment>;
        const src = map?.[part.index];
        let label = `Variable ${part.index + 1}`;
        if (src?.value) {
          label = src.source === "field" ? (fields?.find((f) => f.key === src.value)?.label ?? src.value) : src.value;
        }
        return (
          <span key={i} className="mx-0.5 inline-block rounded-md bg-primary-100 px-1.5 py-0.5 text-xs font-bold text-primary-dark">
            {label}
          </span>
        );
      })}
    </p>
  );
}

/** One source picker per {#var#}: a contact field (name, phone, an extra column) or fixed text. */
export function VariableMapper({
  varCount,
  varMap,
  fields,
  onSet,
}: {
  varCount: number;
  varMap: (SmsVarSource | null)[];
  fields: { key: string; label: string }[];
  onSet: (index: number, value: SmsVarSource | null) => void;
}) {
  return (
    <div className="space-y-3">
      {Array.from({ length: varCount }, (_, i) => {
        const cur = varMap[i];
        const mode = cur ? (cur.source === "field" ? cur.value : FIXED) : "";
        return (
          <div key={i} className="grid gap-2 sm:grid-cols-[110px_minmax(0,1fr)_minmax(0,1fr)] sm:items-end">
            <p className="text-sm font-bold text-[#0A1528] sm:pb-2.5">Variable {i + 1}</p>
            <Field label="Use">
              <select
                className={inputCls}
                value={mode}
                onChange={(e) => {
                  const v = e.target.value;
                  if (!v) onSet(i, null);
                  else if (v === FIXED) onSet(i, { source: "text", value: cur?.source === "text" ? cur.value : "" });
                  else onSet(i, { source: "field", value: v });
                }}
              >
                <option value="">Choose…</option>
                {fields.map((f) => (
                  <option key={f.key} value={f.key}>
                    {f.label}
                  </option>
                ))}
                <option value={FIXED}>Fixed text for everyone</option>
              </select>
            </Field>
            {cur?.source === "text" && (
              <Field label="Text">
                <input className={inputCls} value={cur.value} maxLength={100} placeholder="e.g. 2 Nov" onChange={(e) => onSet(i, { source: "text", value: e.target.value })} />
              </Field>
            )}
          </div>
        );
      })}
    </div>
  );
}
