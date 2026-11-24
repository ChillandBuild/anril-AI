"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Loader2, Search, X } from "lucide-react";
import { API_URL, getAuthHeaders } from "@/lib/api";
import type { Template } from "../types";
import { languageName } from "../types";

/** "Copy one of mine" on Create Template: search this account's templates and start from one. */
export default function CopyPicker({ onPick, onClose }: { onPick: (t: Template) => void; onClose: () => void }) {
  const [list, setList] = useState<Template[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const box = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const res = await fetch(`${API_URL}/api/v1/templates/`, { headers: await getAuthHeaders() });
        if (!res.ok) throw new Error();
        const data = await res.json();
        if (live) setList((data.data ?? []) as Template[]);
      } catch {
        if (live) setError("Couldn't load your templates. Please try again.");
      }
    })();
    input.current?.focus();
    return () => { live = false; };
  }, []);

  useEffect(() => {
    const away = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) onClose(); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", esc); };
  }, [onClose]);

  const shown = useMemo(() => {
    const term = q.trim().toLowerCase();
    return (list ?? []).filter((t) => !term || t.name.toLowerCase().includes(term) || t.body_text.toLowerCase().includes(term)).slice(0, 40);
  }, [list, q]);

  return (
    <div ref={box} role="dialog" aria-label="Copy one of your templates" className="absolute left-0 top-12 z-30 w-[min(420px,calc(100vw-48px))] overflow-hidden rounded-2xl border border-[#e2e8f0] bg-white shadow-xl">
      <div className="flex items-center gap-2 border-b border-[#f1f5f9] px-3 py-2.5">
        <Search size={14} className="shrink-0 text-ink-muted" aria-hidden="true" />
        <input
          ref={input}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search your templates"
          aria-label="Search your templates"
          className="min-w-0 flex-1 bg-transparent text-sm text-ink placeholder:text-ink-muted focus:outline-none"
        />
        <button type="button" onClick={onClose} aria-label="Close" className="rounded-lg p-1 text-ink-muted hover:bg-[#f8fafc] hover:text-ink">
          <X size={14} />
        </button>
      </div>
      <div className="max-h-80 overflow-y-auto py-1">
        {error ? (
          <p className="px-4 py-6 text-center text-sm text-red-700">{error}</p>
        ) : list === null ? (
          <p className="flex items-center justify-center gap-2 px-4 py-6 text-sm text-ink-muted"><Loader2 size={14} className="animate-spin" /> Loading…</p>
        ) : shown.length === 0 ? (
          <p className="px-4 py-6 text-center text-sm text-ink-muted">{list.length ? "No template matches." : "You have no templates yet."}</p>
        ) : (
          shown.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => onPick(t)}
              className="block w-full px-4 py-2.5 text-left transition-colors hover:bg-primary-50/60"
            >
              <span className="flex items-baseline justify-between gap-3">
                <span className="truncate font-mono text-[13px] font-semibold text-ink">{t.name}</span>
                <span className="shrink-0 text-[11.5px] text-ink-muted">
                  {t.category.charAt(0) + t.category.slice(1).toLowerCase()} · {languageName(t.language)}
                </span>
              </span>
              <span className="mt-0.5 block truncate text-[12.5px] text-ink-secondary">{t.body_text}</span>
            </button>
          ))
        )}
      </div>
    </div>
  );
}
