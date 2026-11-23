"use client";
import { useEffect, useState } from "react";
import { Phone } from "lucide-react";
import type { Lead } from "@/lib/api";
import { SEGMENT_WORD, lookupCustomers, worthLooking, type DialMatch } from "../lib/dialLookup";
import type { CallingCockpit } from "../lib/useCallingCockpit";

/** Customers that match what is typed on the Dial a number pad. A card calls by customer, so a hidden number still works. */
export default function DialMatches({ cockpit, readOnly }: { cockpit: CallingCockpit; readOnly: boolean }) {
  const text = cockpit.manualPhone;
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
      {matches.map((m) => (
        <li key={m.id} className="flex items-center justify-between gap-2 rounded-2xl border border-[#e2e8f0] bg-white px-3 py-2.5 shadow-sm">
          <button
            type="button"
            disabled={readOnly || m.phone_hidden || !m.phone}
            onClick={() => m.phone && cockpit.setManualPhone(m.phone)}
            className="min-w-0 flex-1 text-left disabled:cursor-default"
            title={m.phone_hidden ? undefined : "Put this number on the pad"}
          >
            <span className="block truncate font-body text-sm font-bold text-[#13284A]">{m.name || "No name"}</span>
            <span className="block truncate font-label text-xs text-[#475569]">
              {m.phone ?? "No number"}
              {m.segment ? ` · ${SEGMENT_WORD[m.segment] ?? m.segment}` : ""}
              {m.is_buyer ? " · Bought before" : ""}
            </span>
          </button>
          <button
            type="button"
            disabled={readOnly || cockpit.dialCountdown !== null}
            onClick={() => cockpit.dialWithGuard(m.id, { id: m.id, name: m.name, phone: m.phone, segment: m.segment ?? "C" } as Lead)}
            aria-label={`Call ${m.name || "this customer"}`}
            className="flex h-9 shrink-0 items-center gap-1.5 rounded-xl bg-primary px-3 font-label text-xs font-bold text-white disabled:opacity-50"
          >
            <Phone size={13} aria-hidden /> Call
          </button>
        </li>
      ))}
    </ul>
  );
}
