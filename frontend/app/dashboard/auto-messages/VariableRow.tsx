"use client";
import type { AutoMessageVariable, AutoMessageVarSource } from "@/lib/api";
import { Select } from "@/components/ui/Select";
import { VAR_SOURCES, inputCls } from "./shared";

const INVALID = "border-danger focus:border-danger";

/** Default fill for the n-th blank: first name for {{1}}, empty fixed text after that. */
export function defaultVariables(count: number): AutoMessageVariable[] {
  return Array.from({ length: count }, (_, i): AutoMessageVariable =>
    i === 0 ? { source: "first_name", fallback: "there" } : { source: "text", value: "" }
  );
}

/** True when a variable can't be saved: fixed text with no text, or an app value with no name. */
export function variableIsIncomplete(v: AutoMessageVariable): boolean {
  if (v.source === "text") return !(v.value ?? "").trim();
  if (v.source === "extra") return !(v.key ?? "").trim();
  return false;
}

function changeSource(prev: AutoMessageVariable, source: AutoMessageVarSource): AutoMessageVariable {
  if (source === "text") return { source, value: "" };
  if (source === "extra") return { source, key: "", fallback: prev.fallback ?? "" };
  return { source, fallback: prev.fallback ?? "" };
}

/** One {{n}} blank, in plain words: where the value comes from, plus the field that source needs. */
export function VariableRow({
  label,
  value,
  onChange,
  showErrors,
  disabled,
}: {
  label: string;
  value: AutoMessageVariable;
  onChange: (v: AutoMessageVariable) => void;
  showErrors: boolean;
  disabled: boolean;
}) {
  const invalid = showErrors && variableIsIncomplete(value);
  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-[56px_minmax(0,1fr)] sm:items-start">
      <span className="font-mono text-xs font-bold text-primary sm:pt-2.5">{label}</span>
      <div className="grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-2">
        <Select
          value={value.source}
          onChange={(v) => onChange(changeSource(value, v as AutoMessageVarSource))}
          aria-label={`What fills ${label}`}
          disabled={disabled}
          options={VAR_SOURCES.map((s) => ({ value: s.id, label: s.label }))}
        />

        {value.source === "text" && (
          <input
            value={value.value ?? ""}
            onChange={(e) => onChange({ ...value, value: e.target.value })}
            placeholder="Fixed text to show"
            aria-label={`Fixed text for ${label}`}
            aria-invalid={invalid}
            aria-required
            maxLength={200}
            disabled={disabled}
            className={`${inputCls} ${invalid ? INVALID : ""}`}
          />
        )}

        {value.source === "extra" && (
          <input
            value={value.key ?? ""}
            onChange={(e) => onChange({ ...value, key: e.target.value })}
            placeholder="Name, e.g. order_id"
            aria-label={`Name of the value your app sends for ${label}`}
            aria-invalid={invalid}
            aria-required
            maxLength={50}
            disabled={disabled}
            className={`${inputCls} font-mono ${invalid ? INVALID : ""}`}
          />
        )}

        {value.source !== "text" && (
          <input
            value={value.fallback ?? ""}
            onChange={(e) => onChange({ ...value, fallback: e.target.value })}
            placeholder="If empty, use… (optional)"
            aria-label={`If ${label} is empty, use`}
            maxLength={200}
            disabled={disabled}
            className={inputCls}
          />
        )}
      </div>
      {invalid && (
        <p role="alert" className="font-body text-xs text-danger sm:col-start-2">
          {value.source === "text" ? "Type the text to show." : "Type the name your app sends, like order_id."}
        </p>
      )}
    </div>
  );
}
