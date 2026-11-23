"use client";

import { CallIqGate, CallIqPage } from "@/components/call-iq/CallIqShell";
import { LiveBoard } from "@/components/call-iq/LiveBoard";
import { canOpenLive } from "@/lib/callIqApi";

export default function CallIqLivePage() {
  return (
    <CallIqGate allow={canOpenLive}>
      <CallIqPage title="Live" intro="Who is on a call, on a break, free or not logged in, right now.">
        <LiveBoard />
      </CallIqPage>
    </CallIqGate>
  );
}
