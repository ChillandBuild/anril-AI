"use client";
import { useState } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { CompanionAppTool } from "@/lib/api";
import { toolNameError } from "@/components/agents/playground";
import { BTN_SECONDARY, INPUT } from "@/components/agents/ui";

/** Tools the business's app would offer, so the owner can test tool calls without their app. Folded away until needed. */
export function AppTools({ tools, onChange }: { tools: CompanionAppTool[]; onChange: (t: CompanionAppTool[]) => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");
  const add = () => {
    const err = toolNameError(name.trim(), tools.map((t) => t.name));
    if (err) return setError(err);
    onChange([...tools, { name: name.trim(), description: description.trim().slice(0, 500) }]);
    setName("");
    setDescription("");
    setError("");
  };
  return (
    <details className="rounded-xl border border-border-subtle px-3.5 py-2.5 text-sm">
      <summary className="cursor-pointer select-none text-ink-secondary">
        Your app&apos;s tools{tools.length > 0 ? ` (${tools.length})` : ""}
      </summary>
      <p className="mb-3 mt-2 text-xs text-ink-muted">Optional. Pretend your app offers these; you answer them by hand.</p>
      {tools.length > 0 && (
        <ul className="mb-3 space-y-1">
          {tools.map((t) => (
            <li key={t.name} className="flex items-center justify-between gap-2 rounded-lg bg-surface-mid px-2 py-1 font-mono text-xs">
              <span className="truncate">{t.name}</span>
              <button type="button" aria-label={`Remove ${t.name}`} onClick={() => onChange(tools.filter((x) => x.name !== t.name))} className="text-ink-muted hover:text-danger">
                <X size={13} aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="space-y-2">
        <input aria-label="Tool name" value={name} onChange={(e) => setName(e.target.value)} placeholder="get_chart" className={cn(INPUT, "font-mono text-xs")} />
        <input aria-label="What it does" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Returns the person's birth chart" className={cn(INPUT, "text-xs")} />
        {error && <p role="alert" className="text-xs text-danger">{error}</p>}
        <button type="button" onClick={add} disabled={!name.trim()} className={cn(BTN_SECONDARY, "min-h-8 w-full")}>
          Add tool
        </button>
      </div>
    </details>
  );
}
