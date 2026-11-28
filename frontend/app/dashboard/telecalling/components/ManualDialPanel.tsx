"use client";
import { useEffect, useState } from "react";
import { Cloud, Smartphone } from "lucide-react";
import DialChecks from "./DialChecks";
import DialMatches from "./DialMatches";
import NumpadDialer from "./NumpadDialer";
import { defaultDialMode, type DialCheckState, type DialMode } from "../lib/dialCheck";
import type { DialMatch } from "../lib/dialLookup";
import type { Lead } from "@/lib/api";
import type { CallingCockpit } from "../lib/useCallingCockpit";

const MODES: { mode: DialMode; label: string; Icon: typeof Cloud }[] = [
  { mode: "office", label: "Office number", Icon: Cloud },
  { mode: "sim", label: "My SIM", Icon: Smartphone },
];

/**
 * The "Manual Dial" panel: a numpad wired to the calling cockpit. Used inside the Dialer
 * (the AdminView / CallerView "Manual Dial" tab). Below xl the right pane is hidden, so the
 * checks show here instead.
 */
export default function ManualDialPanel({
  cockpit,
  readOnly,
  dialCheck,
  yourName,
  todayBy,
}: {
  cockpit: CallingCockpit;
  readOnly: boolean;
  dialCheck: DialCheckState;
  yourName?: string | null;
  todayBy?: string;
}) {
  const { manualPhone, setManualPhone, dialMode, setDialMode } = cockpit;
  const blocked = dialCheck.check && !dialCheck.check.can_call ? dialCheck.check.blocked_reason : null;
  // The customer picked from the matches. It only counts while the pad still shows the text it was picked at.
  const [picked, setPicked] = useState<{ match: DialMatch; text: string } | null>(null);
  const selected = picked && picked.text === manualPhone ? picked.match : null;

  // Until the person chooses, the pad follows the check's answer for them (else the business setting).
  const fallbackMode = defaultDialMode(dialCheck.check?.calling_from, cockpit.callingProvider);
  const checkedFrom = dialCheck.check?.calling_from ?? null;
  useEffect(() => {
    if (dialMode === null && checkedFrom) setDialMode(checkedFrom);
  }, [dialMode, checkedFrom, setDialMode]);
  const chosen = dialMode ?? fallbackMode;
  const officeReady = dialCheck.check?.office_ready ?? cockpit.officeReady;

  function onPick(m: DialMatch) {
    if (selected?.id === m.id) {
      setPicked(null);
      return;
    }
    const text = m.phone_hidden || !m.phone ? manualPhone : m.phone;
    if (text !== manualPhone) setManualPhone(text);
    setPicked({ match: m, text });
  }

  function onCall() {
    if (selected) {
      cockpit.dialWithGuard(selected.id, { id: selected.id, name: selected.name, phone: selected.phone, segment: selected.segment ?? "C" } as Lead, true);
    } else {
      cockpit.manualDialWithGuard();
    }
  }

  return (
    <div className="flex-1 overflow-y-auto flex flex-col items-center pt-4 pb-2">
      <div className="w-full" title={blocked ?? undefined}>
        <NumpadDialer
          value={manualPhone}
          onChange={setManualPhone}
          onDial={onCall}
          dialing={cockpit.manualDialing}
          disabled={readOnly}
          hasSelection={selected !== null}
        />
      </div>
      <div role="group" aria-label="Call from" className="mx-auto mt-2 grid w-full max-w-[280px] grid-cols-2 gap-2">
        {MODES.map(({ mode, label, Icon }) => {
          const on = chosen === mode;
          const unavailable = mode === "office" && !officeReady;
          return (
            <button
              key={mode}
              type="button"
              aria-pressed={on}
              disabled={readOnly || unavailable}
              title={unavailable ? "Office number isn't set up yet" : undefined}
              onClick={() => setDialMode(mode)}
              className={`flex h-10 items-center justify-center gap-1.5 rounded-xl border px-2 font-label text-xs font-bold transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${on ? "border-primary bg-primary/10 text-primary" : "border-[#e2e8f0] bg-white text-[#475569]"}`}
            >
              <Icon size={14} aria-hidden /> {label}
            </button>
          );
        })}
      </div>
      {!officeReady && <p className="mt-1 font-label text-[10px] text-[#94a3b8]">Office number isn&apos;t set up yet</p>}
      <DialMatches text={manualPhone} readOnly={readOnly} selectedId={selected?.id ?? null} onSelect={onPick} />
      <div className="mt-3 w-full px-1 xl:hidden">
        <DialChecks phone={manualPhone} dial={dialCheck} yourName={yourName} todayBy={todayBy} />
      </div>
    </div>
  );
}
