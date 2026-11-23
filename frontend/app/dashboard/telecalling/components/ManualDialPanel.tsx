"use client";
import DialMatches from "./DialMatches";
import NumpadDialer from "./NumpadDialer";
import type { CallingCockpit } from "../lib/useCallingCockpit";

/**
 * The "Manual Dial" panel: a numpad wired to the calling cockpit. Used inside the Dialer
 * (AdminView / CallerView tab) and on its own at /dashboard/telecalling/dial.
 */
export default function ManualDialPanel({ cockpit, readOnly }: { cockpit: CallingCockpit; readOnly: boolean }) {
  return (
    <div className="flex-1 overflow-y-auto flex flex-col items-center pt-4 pb-2">
      <NumpadDialer
        value={cockpit.manualPhone}
        onChange={cockpit.setManualPhone}
        onDial={cockpit.manualDialWithGuard}
        dialing={cockpit.manualDialing}
        disabled={readOnly}
      />
      <DialMatches cockpit={cockpit} readOnly={readOnly} />
    </div>
  );
}
