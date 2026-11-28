"use client";
import { useEffect, useState } from "react";
import { Check } from "lucide-react";
import { SEGMENT_WORD, lookupCustomers, worthLooking, type DialMatch } from "../lib/dialLookup";

/** Customers that match what is typed on the Manual Dial pad. Tap one to pick it; the big Call Now button then calls that customer by id, so a hidden number still works. */
export default function DialMatches({
  text,
  readOnly,
  selectedId,
  onSelect,
}: {
  text: string;
  readOnly: boolean;
  selectedId: string | null;
  onSelect: (match: DialMatch) => void;
}) {
  const [found, setFound] = useState<{ for: string; matches: DialMatch[] } | null>(null);

  useEffect(() => {
    if (!worthLooking(text)) return;
    let stale = false;
    const t = setTimeout(() => {
      lookupCustomers(text)
        .then((res) => {
          if (!stale) setFound({ for: text, matches: res.matches });
        })
        .catch(() => {
          if (!stale) setFound({ for: text, matches: [] });
        });
    }, 300);
    return () => {
      stale = true;
      clearTimeout(t);
    };
  }, [text]);

  const matches = worthLooking(text) && found?.for === text ? found.matches : [];
  if (matches.length === 0) return null;

  return (
    <ul aria-label="Matching customers" className="mx-auto mt-3 w-full max-w-[280px] space-y-2">
      {matches.map((m) => {
        const selected = m.id === selectedId;
        return (
          <li key={m.id}>
            <button
              type="button"
              disabled={readOnly}
              aria-pressed={selected}
              onClick={() => onSelect(m)}
              className={`flex w-full items-center justify-between gap-2 rounded-2xl border bg-white px-3 py-2.5 text-left shadow-sm disabled:cursor-default ${selected ? "border-primary ring-1 ring-primary" : "border-[#e2e8f0]"}`}
            >
              <span className="min-w-0 flex-1">
                <span className="block truncate font-body text-sm font-bold text-[#13284A]">{m.name || "No name"}</span>
                <span className="block truncate font-label text-xs text-[#475569]">
                  {m.phone ?? "No number"}
                  {m.segment ? ` · ${SEGMENT_WORD[m.segment] ?? m.segment}` : ""}
                  {m.is_buyer ? " · Bought before" : ""}
                </span>
              </span>
              {selected && <Check size={16} className="shrink-0 text-primary" aria-label="Selected" />}
            </button>
          </li>
        );
      })}
    </ul>
  );
}
