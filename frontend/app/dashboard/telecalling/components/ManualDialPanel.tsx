"use client";
import DialChecks from "./DialChecks";
import DialMatches from "./DialMatches";
import NumpadDialer from "./NumpadDialer";
import { callingFromLabel, type DialCheckState } from "../lib/dialCheck";
import type { CallingCockpit } from "../lib/useCallingCockpit";

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
  const blocked = dialCheck.check && !dialCheck.check.can_call ? dialCheck.check.blocked_reason : null;
  return (
    <div className="flex-1 overflow-y-auto flex flex-col items-center pt-4 pb-2">
      <div className="w-full" title={blocked ?? undefined}>
        <NumpadDialer
          value={cockpit.manualPhone}
          onChange={cockpit.setManualPhone}
          onDial={cockpit.manualDialWithGuard}
          dialing={cockpit.manualDialing}
          disabled={readOnly}
        />
      </div>
      <p className="mt-2 font-label text-[11px] text-[#475569]">
        Calling from: {callingFromLabel(dialCheck.check?.calling_from ?? (cockpit.callingProvider === "sim_basic" ? "sim" : "office"))}
      </p>
      <DialMatches cockpit={cockpit} readOnly={readOnly} />
      <div className="mt-3 w-full px-1 xl:hidden">
        <DialChecks phone={cockpit.manualPhone} dial={dialCheck} yourName={yourName} todayBy={todayBy} />
      </div>
    </div>
  );
}
