"use client";

import type { SmsVarSource } from "@/lib/api";
import { Select } from "@/components/ui/Select";
import { Field, inputCls } from "./ui";

const FIXED = "__fixed__";
const TYPED = "__typed__";

/**
 * One source picker per {#var#}: a contact field (name, phone, an extra column), fixed text, or
 * "Type for each number" (a value typed next to each number; only offered when `allowTyped`).
 */
export function VariableMapper({
  varCount,
  varMap,
  fields,
  allowTyped,
  onSet,
}: {
  varCount: number;
  varMap: (SmsVarSource | null)[];
  fields: { key: string; label: string }[];
  allowTyped: boolean;
  onSet: (index: number, value: SmsVarSource | null) => void;
}) {
  return (
    <div className="space-y-3">
      {Array.from({ length: varCount }, (_, i) => {
        const cur = varMap[i];
        const mode = cur ? (cur.source === "field" ? cur.value : cur.source === "typed" ? TYPED : FIXED) : "";
        return (
          <div key={i} className="grid gap-2 sm:grid-cols-[110px_minmax(0,1fr)_minmax(0,1fr)] sm:items-end">
            <p className="text-sm font-bold text-[#0A1528] sm:pb-2.5">Variable {i + 1}</p>
            <Field label="Use">
              <Select
                value={mode}
                onChange={(v) => {
                  if (!v) onSet(i, null);
                  else if (v === TYPED) onSet(i, { source: "typed", value: "" });
                  else if (v === FIXED) onSet(i, { source: "text", value: cur?.source === "text" ? cur.value : "" });
                  else onSet(i, { source: "field", value: v });
                }}
                placeholder="Choose…"
                options={[
                  { value: "", label: "Choose…" },
                  ...fields.map((f) => ({ value: f.key, label: f.label })),
                  ...(allowTyped ? [{ value: TYPED, label: "Type for each number" }] : []),
                  { value: FIXED, label: "Fixed text for everyone" },
                ]}
              />
            </Field>
            {cur?.source === "text" && (
              <Field label="Text">
                <input className={inputCls} value={cur.value} maxLength={100} placeholder="e.g. 2 Nov" onChange={(e) => onSet(i, { source: "text", value: e.target.value })} />
              </Field>
            )}
            {cur?.source === "typed" && <p className="text-xs text-[#64748b] sm:pb-2.5">Type it next to each number in step 2.</p>}
          </div>
        );
      })}
    </div>
  );
}
